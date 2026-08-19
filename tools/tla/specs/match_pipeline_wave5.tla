----------------------------- MODULE match_pipeline_wave5 -----------------------------
EXTENDS Naturals

(*
Wave-5: End-to-end match pipeline (queue + cache + visibility).

Invariants:
  - NoLoss: if DB version ahead, demande is queued.
  - Consistency: when queue empty, cache matches DB.
  - Pairs ⊆ Compat and visible pairs always active.
*)

CONSTANTS DEMANDES, OFFERS, COMPAT

VARIABLES db, cache, queue, activeD, activeO, pairs

Init ==
    /\ db = [d \in DEMANDES |-> 0]
    /\ cache = [d \in DEMANDES |-> 0]
    /\ queue = {}
    /\ activeD \subseteq DEMANDES
    /\ activeO \subseteq OFFERS
    /\ pairs \subseteq COMPAT

Update(d) ==
    /\ d \in DEMANDES
    /\ db' = [db EXCEPT ![d] = @ + 1]
    /\ queue' = queue \cup {d}
    /\ cache' = cache
    /\ activeD' = activeD
    /\ activeO' = activeO
    /\ pairs' = pairs

Process(d) ==
    /\ d \in queue
    /\ cache' = [cache EXCEPT ![d] = db[d]]
    /\ queue' = queue \ {d}
    /\ db' = db
    /\ activeD' = activeD
    /\ activeO' = activeO
    /\ pairs' \subseteq COMPAT

DeactivateDemande(d) ==
    /\ d \in activeD
    /\ activeD' = activeD \ {d}
    /\ activeO' = activeO
    /\ db' = db
    /\ cache' = cache
    /\ queue' = queue
    /\ pairs' = pairs

DeactivateOffer(o) ==
    /\ o \in activeO
    /\ activeO' = activeO \ {o}
    /\ activeD' = activeD
    /\ db' = db
    /\ cache' = cache
    /\ queue' = queue
    /\ pairs' = pairs

Next ==
    \E d \in DEMANDES : Update(d) \/ Process(d) \/ DeactivateDemande(d)
    \/ \E o \in OFFERS : DeactivateOffer(o)

VisiblePairs ==
    {p \in pairs: p[1] \in activeD /\ p[2] \in activeO}

Consistency ==
    (queue = {}) => (\A d \in DEMANDES : cache[d] = db[d])

NoLoss ==
    \A d \in DEMANDES : (db[d] > cache[d]) => d \in queue

VisibilitySafe ==
    \A p \in VisiblePairs : p \in COMPAT

PairsSubset ==
    pairs \subseteq COMPAT

Spec ==
    Init /\ [][Next]_<<db, cache, queue, activeD, activeO, pairs>>

THEOREM Spec => []Consistency
THEOREM Spec => []NoLoss
THEOREM Spec => []VisibilitySafe
THEOREM Spec => []PairsSubset

=====================================================================================
