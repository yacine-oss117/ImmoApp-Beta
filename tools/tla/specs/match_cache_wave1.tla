------------------------------ MODULE match_cache_wave1 ------------------------------
EXTENDS Naturals

CONSTANTS DEMANDES

VARIABLES db, cache, queue

Init ==
    /\ db = [d \in DEMANDES |-> 0]
    /\ cache = [d \in DEMANDES |-> 0]
    /\ queue = {}

Update(d) ==
    /\ d \in DEMANDES
    /\ db' = [db EXCEPT ![d] = @ + 1]
    /\ queue' = queue \cup {d}
    /\ cache' = cache

Process(d) ==
    /\ d \in queue
    /\ cache' = [cache EXCEPT ![d] = db[d]]
    /\ queue' = queue \ {d}
    /\ db' = db

Next ==
    \E d \in DEMANDES : Update(d) \/ Process(d)

Consistency ==
    (queue = {}) => (\A d \in DEMANDES : cache[d] = db[d])

NoLoss ==
    \A d \in DEMANDES : (db[d] > cache[d]) => d \in queue

Spec ==
    Init /\ [][Next]_<<db, cache, queue>>

==============================================================================
