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


def with_torch(test):
    @functools.wraps(test)
    def wrapped(self):
        if importlib.util.find_spec("torch"):
            return test(self)
        python=pipeline.ROOT/"runtime/skapp/venv/bin/python"
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


if __name__=="__main__":unittest.main()
