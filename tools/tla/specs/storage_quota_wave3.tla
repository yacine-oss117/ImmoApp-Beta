----------------------------- MODULE storage_quota_wave3 -----------------------------
EXTENDS Integers, TLC

(*
Wave-3: Storage quota + reservation correctness.
We model a single-tenant quota with two buckets:
  - pending: bytes reserved by in-flight uploads
  - ready: bytes committed after finalize

Invariant: ready + pending never exceeds quota, and never goes negative.
*)

CONSTANTS Quota, Sizes

VARIABLES ready, pending

Init ==
    /\ ready = 0
    /\ pending = 0

CanStart(sz) == ready + pending + sz <= Quota
CanComplete(sz) == pending >= sz
CanFail(sz) == pending >= sz
CanDelete(sz) == ready >= sz

StartUpload(sz) ==
    /\ sz \in Sizes
    /\ CanStart(sz)
    /\ pending' = pending + sz
    /\ ready' = ready

CompleteUpload(sz) ==
    /\ sz \in Sizes
    /\ CanComplete(sz)
    /\ pending' = pending - sz
    /\ ready' = ready + sz

FailUpload(sz) ==
    /\ sz \in Sizes
    /\ CanFail(sz)
    /\ pending' = pending - sz
    /\ ready' = ready

DeleteReady(sz) ==
    /\ sz \in Sizes
    /\ CanDelete(sz)
    /\ ready' = ready - sz
    /\ pending' = pending

Next ==
    \E sz \in Sizes :
        StartUpload(sz)
        \/ CompleteUpload(sz)
        \/ FailUpload(sz)
        \/ DeleteReady(sz)

Inv ==
    /\ ready >= 0
    /\ pending >= 0
    /\ ready + pending <= Quota

Spec ==
    Init /\ [][Next]_<<ready, pending>>

THEOREM Spec => []Inv

=====================================================================================
