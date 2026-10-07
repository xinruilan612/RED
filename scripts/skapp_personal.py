"""Train the vendored SKAPP architecture on fixed-window personal or shared labels.

Encoded JSON is the boundary: vectors must come from the declared ChineseCLIP
encoder. No web collection, label synthesis or paid model calls occur here.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "third_party/skapp/src"
ENCODER = "OFA-Sys/chinese-clip-vit-base-patch16"
MIN_RECORDS = 100  # Engineering gate only; not statistical evidence.


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def upstream_hash():
    return {name: digest(VENDOR / name) for name in
            ("model.py", "teachers.py", "teacher_graph.py")}


def libraries():
    import torch
    sys.path.insert(0, str(VENDOR)) if str(VENDOR) not in sys.path else None
    from model import SKAPP
    from teachers import Teacher, predict_single_item_delta
    return torch, SKAPP, Teacher, predict_single_item_delta


def stamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps require a timezone")
    return parsed.timestamp()


def vector(value, dim):
    if not isinstance(value, list) or len(value) != dim:
        raise ValueError(f"Both image and text require {dim}-dimensional vectors")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in value):
        raise ValueError("Vectors must be finite numbers")
    norm = math.sqrt(sum(v*v for v in value))
    if not math.isfinite(norm) or norm < 1e-9:
        raise ValueError("Empty vector")
    return [v/norm for v in value]


def corpus_fingerprint(data):
    """Public corpus identity is independent of any website account history."""
    keys = ("schema_version", "model_scope", "data_scope", "encoder_id", "platform", "target_metric", "window_hours", "dataset_license", "records")
    payload = {key: data.get(key) for key in keys}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate(data, dim=512, minimum=MIN_RECORDS):
    if data.get("schema_version") != 1 or data.get("encoder_id") != ENCODER:
        raise ValueError("Unsupported schema or encoder")
    model_scope = data.get("model_scope", "personal")
    if model_scope not in ("shared", "personal"):
        raise ValueError("Unsupported model scope")
    shared = model_scope == "shared"
    scope = data.get("scope_digest", "")
    if shared:
        if data.get("data_scope") != "licensed_public" or data.get("platform") not in ("xiaohongshu", "douyin"):
            raise ValueError("Shared training requires licensed_public supported-platform data")
        if not isinstance(data.get("dataset_license"), str) or not data["dataset_license"].strip():
            raise ValueError("dataset_license must state permission; this declaration is not legal verification")
    else:
        history = data.get("training_history_digest", "")
        if len(history) != 64 or any(c not in "0123456789abcdef" for c in history):
            raise ValueError("Invalid training history snapshot digest")
        if len(scope) != 64 or any(c not in "0123456789abcdef" for c in scope):
            raise ValueError("Invalid account scope")
    if data.get("target_metric") not in ("reads", "views", "likes", "saves", "comments", "shares"):
        raise ValueError("Unsupported observed target metric")
    window = data.get("window_hours")
    if isinstance(window, bool) or not isinstance(window, (int, float)) or not 1 <= window <= 2160:
        raise ValueError("Invalid observation window")
    rows = copy.deepcopy(data.get("records", []))
    if len(rows) < minimum:
        raise ValueError(f"Insufficient fixed-window records: need at least {minimum}; this is only an engineering minimum")
    ids = set()
    for row in rows:
        if not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids:
            raise ValueError("Record IDs must be unique")
        ids.add(row["id"])
        row["author_id"] = row.get("author_id") if shared else (row.get("author_id") or scope)
        if not isinstance(row["author_id"], str) or not row["author_id"].strip():
            raise ValueError("Invalid author ID")
        if not str(row.get("source_url", "")).startswith(("https://", "http://")):
            raise ValueError("Each real observation needs a source URL")
        if shared:
            # A website account is never assumed to be a corpus author.
            row["author_id"] = "corpus:" + row["author_id"]
            row["profile_vector"] = vector(row.get("profile_vector"), dim)
        row["published_ts"] = stamp(row["published_at"])
        if shared:
            profile_time = row.get("profile_observed_at") or row.get("profile_asof")
            if not isinstance(profile_time, str) or stamp(profile_time) > row["published_ts"]:
                raise ValueError("Shared profile requires profile_observed_at no later than publication")
        row["observed_ts"] = stamp(row["observed_at"])
        if row["observed_ts"] > datetime.now(timezone.utc).timestamp():
            raise ValueError("Future observations cannot be training labels")
        elapsed = (row["observed_ts"]-row["published_ts"])/3600
        if abs(elapsed-window) > window*.05:
            raise ValueError("Observation does not match the fixed window (+/-5%)")
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("Missing or invalid observed label; never fill missing counts with zero")
        row["visual"] = vector(row.get("visual"), dim)
        row["textual"] = vector(row.get("textual"), dim)
    return sorted(rows, key=lambda r: (r["published_ts"], r["id"]))


def neighbors(query, pool, k, cutoff=None):
    cutoff = query.get("published_ts", float("inf")) if cutoff is None else cutoff
    eligible = [r for r in pool if r["id"] != query["id"] and r["observed_ts"] < cutoff]
    def score(row):
        base = sum(a*b for a,b in zip(query["visual"], row["visual"])) + sum(a*b for a,b in zip(query["textual"], row["textual"]))
        # Same retrieval policy in training and inference. Profile is pre-publication
        # positioning encoded with the same ChineseCLIP text encoder, never labels.
        return base + sum(a*b for a,b in zip(query.get("profile_vector", []), row["textual"]))
    return sorted(eligible, key=lambda r: (-score(r), r["id"]))[:k]


def temporal_split(rows, k):
    a, b = int(len(rows)*.7), int(len(rows)*.85)
    pool = [r for r in rows[:a] if r["observed_ts"] < rows[a]["published_ts"]]
    valid = [r for r in rows[a:b] if r["observed_ts"] < rows[b]["published_ts"]]
    groups = [[(r, neighbors(r, pool, k)) for r in part] for part in (pool, valid, rows[b:])]
    groups = [[pair for pair in group if len(pair[1]) == k] for group in groups]
    if len(groups[0]) < 8 or min(map(len, groups[1:])) < 3:
        raise ValueError("Not enough temporally eligible training/validation/test records after warmup")
    return pool, groups


def tensors(pairs, mean, std):
    torch, *_ = libraries()
    make = lambda x: torch.tensor(x, dtype=torch.float32)
    qv=make([r["visual"] for r,n in pairs]); qt=make([r["textual"] for r,n in pairs])
    nv=make([[v["visual"] for v in n] for r,n in pairs]); nt=make([[v["textual"] for v in n] for r,n in pairs])
    labels=make([[(math.log1p(v["value"])-mean)/std for v in n] for r,n in pairs])
    vi=(qv[:,None,:]*nv).sum(-1); tx=(qt[:,None,:]*nt).sum(-1)
    scores=vi+tx
    profile_scores=make([[sum(a*b for a,b in zip(r.get("profile_vector", []), v["textual"])) for v in n] for r,n in pairs])
    scores=scores+profile_scores
    scores=((scores-scores.mean(1,keepdim=True))/scores.std(1,keepdim=True,unbiased=False).clamp_min(.001)).clamp(-5,5)
    same_author=make([[float(r.get("author_id")==v.get("author_id")) for v in n] for r,n in pairs])
    relations=torch.stack((vi,tx,scores,same_author),dim=-1)
    return qv,qt,nv,nt,labels,relations


def teacher_inputs(inputs, mean=0., std=1.):
    qv,qt,nv,nt,labels,*_=inputs
    return qv[:,None,:],qt[:,None,:],nv,nt,labels*std+mean


def rrcp_values(all_model, single_model, inputs, mean=0., std=1.):
    torch, _, _, delta = libraries()
    all_model.eval(); single_model.eval()
    with torch.no_grad():
        ti=teacher_inputs(inputs,mean,std)
        target=all_model(*ti).reshape(-1,1)
        without, with_neighbor=delta(single_model,ti[0],ti[1],ti[2].unsqueeze(2),ti[3].unsqueeze(2),ti[4])
        return (target-without).abs()-(target-with_neighbor).abs()


def fit(model, train_x, train_y, valid_x, valid_y, epochs, single=False, student=False):
    torch, *_=libraries()
    optimizer=(torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=1e-3) if student else torch.optim.Adam(model.parameters(),lr=1e-4))
    best=float("inf"); state=None
    for epoch in range(epochs):
        model.train()
        for indices in torch.randperm(len(train_y)).split(8):
            x=[a[indices] for a in train_x]
            if student:
                prediction,query,_=model(*x,return_details=True)
                loss=(prediction.flatten()-train_y[indices]).square().mean()+.1*(query.flatten()-train_y[indices]).square().mean()
            else:
                prediction=model(*x).flatten()
                loss=(prediction-train_y[indices]).square().mean()
                if single:
                    loss=.5*loss+.5*(model.forward_query_only(x[0],x[1]).flatten()-train_y[indices]).square().mean()
            if not torch.isfinite(loss): raise ValueError("Non-finite training loss")
            optimizer.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),5.); optimizer.step()
        model.eval()
        with torch.no_grad():
            error=(model(*valid_x).flatten()-valid_y).square().mean()
            if single: error=.5*error+.5*(model.forward_query_only(valid_x[0],valid_x[1]).flatten()-valid_y).square().mean()
            error=float(error)
        if error < best: best=error; state=copy.deepcopy(model.state_dict())
    model.load_state_dict(state)
    return model.eval()


def single_inputs(inputs):
    torch, *_=libraries()
    qv,qt,nv,nt,labels=inputs
    n,k=labels.shape
    return [qv.repeat_interleave(k,0),qt.repeat_interleave(k,0),nv.reshape(n*k,1,-1),nt.reshape(n*k,1,-1),labels.reshape(n*k,1)]


def train(data, bundle, epochs=10, k=5, dim=512, minimum=MIN_RECORDS, synthetic=False):
    synthetic = synthetic or data.get("synthetic") is True
    if not 1 <= epochs <= 200 or not 1 <= k <= 50: raise ValueError("epochs 1..200, neighbors 1..50")
    if Path(bundle).exists(): raise ValueError("Bundle already exists; use a new version directory")
    rows=validate(data,dim,minimum); pool,groups=temporal_split(rows,k)
    torch,SKAPP,Teacher,_=libraries(); torch.manual_seed(12); torch.set_num_threads(2)
    raw=torch.tensor([math.log1p(r["value"]) for r in pool])
    mean=float(raw.mean()); std=max(float(raw.std(unbiased=False)),.001)
    xs=[tensors(g,mean,std) for g in groups]
    ys=[torch.tensor([(math.log1p(r["value"])-mean)/std for r,n in g]) for g in groups]
    ti=[teacher_inputs(x,mean,std) for x in xs]
    teacher_y=[y*std+mean for y in ys]
    all_model=fit(Teacher(k,feature_dim=dim,efficient=True),ti[0],teacher_y[0],ti[1],teacher_y[1],epochs)
    si=[single_inputs(x) for x in ti]
    single_model=fit(Teacher(1,feature_dim=dim,efficient=True),si[0],teacher_y[0].repeat_interleave(k),si[1],teacher_y[1].repeat_interleave(k),epochs,single=True)
    rr=[rrcp_values(all_model,single_model,x,mean,std) for x in xs]
    scale=max(float(rr[0].std(unbiased=False)),.001)
    sx=[[*x,r/scale] for x,r in zip(xs,rr)]
    student=fit(SKAPP(feature_dim=dim),sx[0],ys[0],sx[1],ys[1],epochs,student=True)
    evaluation={}
    with torch.no_grad():
        for name,x,y in zip(("train","valid","test"),sx,ys):
            pred=student(*x).flatten(); evaluation[name]={"count":len(y),"log1p_mse":float(((pred-y)*std).square().mean()),"constant_log1p_mse":float((y*std).square().mean())}
    ready=not synthetic and evaluation["valid"]["log1p_mse"] < evaluation["valid"]["constant_log1p_mse"]
    destination=Path(bundle)
    if destination.exists(): raise ValueError("Bundle already exists; use a new version directory")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        folder=Path(tmp)/"bundle"; folder.mkdir()
        torch.save({"student":student.state_dict(),"all_teacher":all_model.state_dict(),"single_teacher":single_model.state_dict()},folder/"weights.pt")
        (folder/"references.json").write_text(json.dumps(pool),encoding="utf-8")
        manifest={key:data[key] for key in ("schema_version","encoder_id","target_metric","window_hours")}
        shared = data.get("model_scope") == "shared"
        if shared:
            manifest.update(model_scope="shared", data_scope="licensed_public", platform=data["platform"],
                            dataset_license=data["dataset_license"], corpus_fingerprint=corpus_fingerprint(data),
                            retrieval_policy="visual_cosine+text_cosine+prepublication_profile_to_reference_text_cosine")
        else:
            manifest.update(scope_digest=data["scope_digest"], training_history_digest=data["training_history_digest"])
        manifest.update(query_author_id=data.get("query_author_id") or data.get("scope_digest", ""),feature_dim=dim,neighbors=k,method="upstream_skapp_shared" if shared else "upstream_skapp_personal",upstream_sha256=upstream_hash(),trained_at=datetime.now(timezone.utc).isoformat(),statistics={"label_log1p_mean":mean,"label_log1p_std":std,"rrcp_scale":scale},evaluation=evaluation,ready_for_prediction=ready,synthetic=synthetic,status="ready" if ready else "trained_unvalidated",training={"epochs":epochs,"seed":12,"relation_features":["visual_cosine","text_cosine","standardized_retrieval_score","same_author"],"engineering_minimum_records":minimum},files={name:digest(folder/name) for name in ("weights.pt","references.json")})
        if shared:
            (folder/"corpus.json").write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            manifest["files"]["corpus.json"] = digest(folder/"corpus.json")
            manifest["training"]["relation_features"][2] = "standardized_profile_aware_retrieval_score"
        (folder/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        os.rename(folder,destination)
    return manifest


def check(bundle):
    folder=Path(bundle); manifest=json.loads((folder/"manifest.json").read_text())
    shared = manifest.get("method") == "upstream_skapp_shared"
    fingerprint = manifest.get("corpus_fingerprint" if shared else "training_history_digest", "")
    if len(fingerprint)!=64 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise ValueError("Model is missing a valid corpus or training history snapshot")
    if shared and (manifest.get("model_scope") != "shared" or manifest.get("data_scope") != "licensed_public" or manifest.get("platform") not in ("xiaohongshu", "douyin") or not str(manifest.get("dataset_license", "")).strip()):
        raise ValueError("Invalid shared model provenance")
    if manifest.get("method") not in ("upstream_skapp_personal", "upstream_skapp_shared") or manifest.get("feature_dim") != 512 or manifest.get("encoder_id") != ENCODER or manifest.get("synthetic"):
        raise ValueError("Not a production ChineseCLIP SKAPP bundle")
    if manifest.get("upstream_sha256") != upstream_hash(): raise ValueError("Vendored architecture fingerprint mismatch")
    files=manifest.get("files",{})
    expected_files = {"weights.pt", "references.json", "corpus.json"} if shared else {"weights.pt", "references.json"}
    if set(files) != expected_files or any(digest(folder/name)!=sha for name,sha in files.items()):
        raise ValueError("Incomplete or modified bundle")
    if shared:
        corpus = json.loads((folder/"corpus.json").read_text())
        if corpus_fingerprint(corpus) != manifest["corpus_fingerprint"]:
            raise ValueError("Shared corpus fingerprint mismatch")
        for key in ("schema_version", "model_scope", "data_scope", "encoder_id", "platform", "target_metric", "window_hours", "dataset_license"):
            if corpus.get(key) != manifest.get(key):
                raise ValueError("Shared corpus metadata mismatch: " + key)
    return manifest


def predict(bundle, data):
    manifest=check(bundle)
    if not manifest.get("ready_for_prediction"): raise ValueError("Model has not passed held-out validation against the constant baseline")
    return _predict_bundle(bundle,data,manifest)


def _predict_bundle(bundle,data,manifest):
    """Internal inference also used by synthetic architecture tests; public predict gates first."""
    dim=manifest["feature_dim"]
    shared = manifest.get("method") == "upstream_skapp_shared"
    keys = ("schema_version", "encoder_id", "target_metric", "window_hours", "platform") if shared else ("schema_version","scope_digest","encoder_id","target_metric","window_hours","training_history_digest")
    if shared:
        if not isinstance(data.get("author_id"), str) or not data["author_id"].strip():
            raise ValueError("Shared query requires an isolated account author_id")
        profile = vector(data.get("profile_vector"), dim)
    for key in keys:
        if data.get(key)!=manifest.get(key): raise ValueError(f"Prediction scope/encoder/metric mismatch: {key}")
    rows=copy.deepcopy(data.get("candidates",[]))
    if not 1<=len(rows)<=10: raise ValueError("Use 1..10 candidates")
    ids=set()
    for r in rows:
        if not isinstance(r.get("id"),str) or r["id"] in ids: raise ValueError("Unique candidate IDs required")
        ids.add(r["id"])
        r["author_id"]=("web:" + data["author_id"]) if shared else (manifest.get("query_author_id") or manifest["scope_digest"])
        if shared: r["profile_vector"] = profile
        for field in ("visual","textual"): r[field]=vector(r.get(field),dim)
    torch,SKAPP,Teacher,_=libraries(); torch.set_num_threads(2)
    pool=json.loads((Path(bundle)/"references.json").read_text()); k=manifest["neighbors"]
    now=datetime.now(timezone.utc).timestamp()
    pairs=[(r,neighbors(r,pool,k,now)) for r in rows]
    if any(len(n)!=k for r,n in pairs): raise ValueError("Not enough eligible observed references")
    stats=manifest["statistics"]; x=tensors(pairs,stats["label_log1p_mean"],stats["label_log1p_std"])
    weights=torch.load(Path(bundle)/"weights.pt",map_location="cpu",weights_only=True)
    student=SKAPP(feature_dim=dim); all_model=Teacher(k,feature_dim=dim,efficient=True); single_model=Teacher(1,feature_dim=dim,efficient=True)
    for model,key in ((student,"student"),(all_model,"all_teacher"),(single_model,"single_teacher")):
        model.load_state_dict(weights[key]); model.eval()
    rr=rrcp_values(all_model,single_model,x,stats["label_log1p_mean"],stats["label_log1p_std"])
    with torch.no_grad(): prediction,_,details=student(*x,rr/stats["rrcp_scale"],return_details=True)
    results=[]
    for i,(r,n) in enumerate(pairs):
        value=float(prediction[i])*stats["label_log1p_std"]+stats["label_log1p_mean"]
        if not math.isfinite(value) or value>80: raise ValueError("Unstable prediction")
        results.append({"id":r["id"],"predicted_value":max(0.,math.expm1(value)),"reference_ids":[v["id"] for v in n],"rrcp":rr[i].tolist(),"attention":details["attention"][i].tolist()})
    return {"schema_version":1,"status":"predicted","method":manifest["method"],"target_metric":manifest["target_metric"],"window_hours":manifest["window_hours"],"candidates":results,"validation":manifest["evaluation"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("train","predict","check")); parser.add_argument("--bundle",required=True)
    parser.add_argument("--input"); parser.add_argument("--output"); parser.add_argument("--epochs",type=int,default=10); parser.add_argument("--neighbors",type=int,default=5)
    args=parser.parse_args()
    try:
        if args.command=="check": result=check(args.bundle)
        else:
            if not args.input: raise ValueError("--input is required")
            data=json.loads(Path(args.input).read_text())
            result=train(data,args.bundle,args.epochs,args.neighbors) if args.command=="train" else predict(args.bundle,data)
        text=json.dumps(result,ensure_ascii=False)
        if args.output: Path(args.output).write_text(text,encoding="utf-8")
        else: print(text)
    except (ValueError,KeyError,OSError,RuntimeError) as exc:
        print(json.dumps({"status":"unavailable","error":str(exc)},ensure_ascii=False),file=sys.stderr); return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
