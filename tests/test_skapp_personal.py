"""Deterministic validation plus small synthetic ORIGINAL architecture smoke test."""
import copy
import importlib.util
import math
from pathlib import Path
import tempfile
import subprocess
import functools
import unittest
from datetime import datetime, timedelta, timezone
from scripts import skapp_personal as pipeline


def dataset(n=40,dim=16):
    start=datetime(2020,1,1,tzinfo=timezone.utc)
    rows=[]
    for i in range(n):
        rows.append({"id":str(i),"published_at":(start+timedelta(days=4*i)).isoformat(),"observed_at":(start+timedelta(days=4*i,hours=72)).isoformat(),"value":10+i%7,"source_url":"https://example.org/synthetic/"+str(i),"visual":[math.sin(i+j+1) for j in range(dim)],"textual":[math.cos(i+j+1) for j in range(dim)]})
    return {"schema_version":1,"scope_digest":"a"*64,"training_history_digest":"b"*64,"encoder_id":pipeline.ENCODER,"target_metric":"views","window_hours":72,"records":rows}


def shared_dataset(n=40, dim=16):
    data=dataset(n,dim)
    data.pop("scope_digest"); data.pop("training_history_digest")
    data.update(model_scope="shared", data_scope="licensed_public", platform="xiaohongshu", dataset_license="Synthetic fixtures only; not production observations")
    for i,row in enumerate(data["records"]):
        row.update(author_id="author-"+str(i%4), profile_vector=list(row["textual"]), profile_observed_at=row["published_at"])
    return data


def with_torch(test):
    @functools.wraps(test)
    def wrapped(self):
        if importlib.util.find_spec("torch"):
            return test(self)
        from backend.python_runtime import venv_python
        python=venv_python(pipeline.ROOT/"runtime/skapp/venv")
        if not python.exists():
            self.fail("SKAPP test runtime missing: install the declared optional environment")
        result=subprocess.run([str(python),"-m","unittest","tests.test_skapp_personal."+type(self).__name__+"."+self._testMethodName,"-v"],cwd=pipeline.ROOT,capture_output=True,text=True,timeout=180)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    return wrapped


class PersonalSKAPPTests(unittest.TestCase):
    def test_insufficient_real_records_refused(self):
        with self.assertRaisesRegex(ValueError,"Insufficient"):
            pipeline.validate(dataset(),16)

    def test_fixed_window_and_missing_labels(self):
        for modification in ({"value":None},{"value":-1},{"visual":[0]*16},{"observed_at":"2020-01-10T00:00:00+00:00"}):
            data=dataset();data["records"][0].update(modification)
            with self.assertRaises(ValueError):pipeline.validate(data,16,30)

    def test_temporal_neighbors_no_self_no_future(self):
        rows=pipeline.validate(dataset(),16,30)
        pool,groups=pipeline.temporal_split(rows,3)
        train_ids={r["id"] for r in pool}
        for group in groups:
            for query,neighbors in group:
                self.assertTrue(all(r["id"] in train_ids and r["id"]!=query["id"] and r["observed_ts"]<query["published_ts"] for r in neighbors))

    def test_daily_fixed_window_purges_split_boundary_leakage(self):
        data=dataset(n=100)
        start=datetime(2020,1,1,tzinfo=timezone.utc)
        for i,row in enumerate(data["records"]):
            row["published_at"]=(start+timedelta(days=i)).isoformat()
            row["observed_at"]=(start+timedelta(days=i,hours=72)).isoformat()
        rows=pipeline.validate(data,16)
        pool,groups=pipeline.temporal_split(rows,3)
        self.assertTrue(all(r["observed_ts"]<rows[70]["published_ts"] for r in pool))
        self.assertTrue(all(r["observed_ts"]<rows[85]["published_ts"] for r,n in groups[1]))

    @with_torch
    def test_upstream_relation_feature_semantics(self):
        torch,*_=pipeline.libraries()
        rows=pipeline.validate(dataset(),16,30);_,groups=pipeline.temporal_split(rows,3)
        *_,rel=pipeline.tensors(groups[1],0.,1.)
        score=rel[:,:,0]+rel[:,:,1]
        expected=((score-score.mean(1,keepdim=True))/score.std(1,keepdim=True,unbiased=False).clamp_min(.001)).clamp(-5,5)
        self.assertTrue(torch.allclose(rel[:,:,2],expected))
        self.assertTrue(torch.equal(rel[:,:,3],torch.ones_like(score)))

    @with_torch
    def test_other_author_relation_is_zero(self):
        rows=pipeline.validate(dataset(),16,30)
        rows[-1]["author_id"]="different-author"
        pairs=[(rows[-1],rows[:3])]
        *_,rel=pipeline.tensors(pairs,0.,1.)
        self.assertEqual(rel[:,:,3].tolist(),[[0.,0.,0.]])

    @with_torch
    def test_production_dimension_synthetic_train_reload_infer(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=dataset(n=100,dim=512); path=Path(tmp)/"model"
            manifest=pipeline.train(data,path,epochs=1,k=5,synthetic=True)
            data["candidates"]=[{"id":"new","visual":data["records"][0]["visual"],"textual":data["records"][0]["textual"],"author_id":"spoof"}]
            result=pipeline._predict_bundle(path,data,manifest)
            self.assertEqual(result["candidates"][0]["id"],"new")
            self.assertEqual(manifest["training_history_digest"],"b"*64)
            self.assertFalse(manifest["ready_for_prediction"])
            with self.assertRaises(ValueError):pipeline.check(path)
            data["training_history_digest"]="c"*64
            with self.assertRaisesRegex(ValueError,"training_history_digest"):
                pipeline._predict_bundle(path,data,manifest)

    @with_torch
    def test_real_teacher_rrcp_student_training_synthetic_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"model"
            result=pipeline.train(dataset(),path,epochs=1,k=2,dim=16,minimum=30,synthetic=True)
            self.assertEqual(result["status"],"trained_unvalidated")
            self.assertFalse(result["ready_for_prediction"])
            self.assertGreater(result["statistics"]["rrcp_scale"],0)
            self.assertTrue(math.isfinite(result["evaluation"]["test"]["log1p_mse"]))
            with self.assertRaisesRegex(ValueError,"production"):
                pipeline.check(path)
            query=dataset(); query["candidates"]=[{"id":"new","visual":query["records"][0]["visual"],"textual":query["records"][0]["textual"]}]
            inferred=pipeline._predict_bundle(path,query,result)
            self.assertEqual(inferred["candidates"][0]["id"],"new")
            self.assertGreaterEqual(inferred["candidates"][0]["predicted_value"],0)
            torch,_,Teacher,_=pipeline.libraries()
            weights=torch.load(path/"weights.pt",weights_only=True)
            all_m=Teacher(2,feature_dim=16,efficient=True);one=Teacher(1,feature_dim=16,efficient=True)
            all_m.load_state_dict(weights["all_teacher"]);one.load_state_dict(weights["single_teacher"])
            rows=pipeline.validate(dataset(),16,30);_,groups=pipeline.temporal_split(rows,2)
            x=pipeline.tensors(groups[1],0.,1.)
            rrcp=pipeline.rrcp_values(all_m,one,x)
            self.assertEqual(tuple(rrcp.shape),(len(groups[1]),2))
            self.assertTrue(torch.isfinite(rrcp).all())
            # RRCP genuinely follows teacher outputs rather than cosine similarity.
            with torch.no_grad():one.predict_linear_2.bias.add_(20.)
            self.assertFalse(torch.allclose(rrcp,pipeline.rrcp_values(all_m,one,x)))


class SharedSKAPPTests(unittest.TestCase):
    def test_shared_requires_declared_provenance_and_prepublication_profile(self):
        valid=shared_dataset()
        rows=pipeline.validate(valid,16,30)
        self.assertTrue(rows[0]["author_id"].startswith("corpus:"))
        for field in ("author_id", "profile_vector", "profile_observed_at", "source_url"):
            data=copy.deepcopy(valid); data["records"][0].pop(field)
            with self.assertRaises(ValueError): pipeline.validate(data,16,30)
        for field in ("dataset_license", "platform", "data_scope"):
            data=copy.deepcopy(valid); data.pop(field)
            with self.assertRaises(ValueError): pipeline.validate(data,16,30)
        data=copy.deepcopy(valid);data["records"][0]["profile_observed_at"]="2021-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"publication"):pipeline.validate(data,16,30)

    def test_shared_fingerprint_independent_of_private_history(self):
        data=shared_dataset(); first=pipeline.corpus_fingerprint(data)
        data.update(scope_digest="x", training_history_digest="different-private-history")
        self.assertEqual(first,pipeline.corpus_fingerprint(data))
        data["records"][0]["value"]+=1
        self.assertNotEqual(first,pipeline.corpus_fingerprint(data))

    @with_torch
    def test_profile_changes_neighbors_and_relation_score_consistently(self):
        query={"id":"q","visual":[1.,0.],"textual":[0.,1.],"profile_vector":[1.,0.],"author_id":"q"}
        pool=[{"id":"a","visual":[1.,0.],"textual":[1.,0.],"observed_ts":0,"value":1,"author_id":"a"},
              {"id":"b","visual":[1.,0.],"textual":[0.,1.],"observed_ts":0,"value":1,"author_id":"b"}]
        query["profile_vector"]=[-1.,0.]
        first=pipeline.neighbors(query,pool,1)[0]["id"]
        query["profile_vector"]=[1.,-1.]
        second=pipeline.neighbors(query,pool,1)[0]["id"]
        self.assertNotEqual(first,second)
        *_,rel=pipeline.tensors([(query,pool)],0.,1.)
        self.assertEqual(rel[0,:,2].tolist(),[1.,-1.])
        self.assertEqual(rel[0,:,3].tolist(),[0.,0.])

    @with_torch
    def test_shared_training_inference_for_two_empty_history_accounts(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            data=shared_dataset();path=Path(tmp)/"shared"
            manifest=pipeline.train(data,path,epochs=1,k=2,dim=16,minimum=30,synthetic=True)
            self.assertEqual(manifest["method"],"upstream_skapp_shared")
            self.assertNotIn("training_history_digest",manifest)
            self.assertEqual(manifest["corpus_fingerprint"],pipeline.corpus_fingerprint(data))
            self.assertFalse(manifest["ready_for_prediction"])
            self.assertIn("corpus.json",manifest["files"])
            query={key:data[key] for key in ("schema_version","encoder_id","platform","target_metric","window_hours")}
            query.update(author_id="first",profile_vector=data["records"][0]["profile_vector"], candidates=[{"id":"new", "visual":data["records"][0]["visual"],"textual":data["records"][0]["textual"],"author_id":"author-0"}])
            original=pipeline.tensors
            observed=[]
            def capture(pairs,*args):
                result=original(pairs,*args); observed.append(result[-1][:,:,3].tolist()); return result
            with patch.object(pipeline,"tensors",side_effect=capture):
                first=pipeline._predict_bundle(path,query,manifest)
                query["author_id"]="second"
                second=pipeline._predict_bundle(path,query,manifest)
            self.assertEqual(first["candidates"],second["candidates"])
            self.assertTrue(all(value==0 for batch in observed for row in batch for value in row))
            query.pop("profile_vector")
            with self.assertRaises(ValueError):pipeline._predict_bundle(path,query,manifest)


if __name__=="__main__":unittest.main()
