----------------------------- MODULE match_counts_wave6 -----------------------------
EXTENDS TLC

(*
Wave-6: Match count cache correctness.
We model candidate edges, active visibility, a rebuild queue,
and a cached count per demande.

Invariants:
  - candidates ⊆ compat
  - if queue empty, cached counts equal active counts
  - if cached count differs, demande is in queue
  - when only active sets shrink and candidates unchanged,
    active counts cannot increase
*)

CONSTANTS Demandes, Offers, Compat

VARIABLES activeD, activeO, candidates, countCache, queue

Init ==
    /\ activeD \subseteq Demandes
    /\ activeO \subseteq Offers
    /\ candidates \subseteq Compat
    /\ countCache = [d \in Demandes |-> 0]
    /\ queue = {}

ActiveCount(d, candSet, actDSet, actOSet) ==
    Cardinality({o \in Offers:
        /\ <<d, o>> \in candSet
        /\ d \in actDSet
        /\ o \in actOSet
    })

UpdateCandidates(d) ==
    /\ d \in Demandes
    /\ candidates' \subseteq Compat
    /\ queue' = queue \cup {d}
    /\ countCache' = countCache
    /\ activeD' = activeD
    /\ activeO' = activeO

Process(d) ==
    /\ d \in queue
    /\ countCache' = [countCache EXCEPT ![d] = ActiveCount(d, candidates, activeD, activeO)]
    /\ queue' = queue \ {d}
    /\ candidates' = candidates
    /\ activeD' = activeD
    /\ activeO' = activeO

DeactivateDemande(d) ==
    /\ d \in activeD
    /\ activeD' = activeD \ {d}
    /\ activeO' = activeO
    /\ candidates' = candidates
    /\ countCache' = countCache
    /\ queue' = queue

DeactivateOffer(o) ==
    /\ o \in activeO
    /\ activeO' = activeO \ {o}
    /\ activeD' = activeD
    /\ candidates' = candidates
    /\ countCache' = countCache
    /\ queue' = queue

Next ==
    \E d \in Demandes : UpdateCandidates(d) \/ Process(d) \/ DeactivateDemande(d)
    \/ \E o \in Offers : DeactivateOffer(o)

CountsConsistent ==
    (queue = {}) => (\A d \in Demandes :
        countCache[d] = ActiveCount(d, candidates, activeD, activeO))

NoLoss ==
    \A d \in Demandes :
        (countCache[d] # ActiveCount(d, candidates, activeD, activeO)) => d \in queue

MonotonicShrink ==
    ( /\ activeD' \subseteq activeD
      /\ activeO' \subseteq activeO
      /\ candidates' = candidates
      /\ countCache' = countCache
      /\ queue' = queue
    )
    => (\A d \in Demandes :
        ActiveCount(d, candidates', activeD', activeO')
        <= ActiveCount(d, candidates, activeD, activeO))

Spec ==
    Init /\ [][Next]_<<activeD, activeO, candidates, countCache, queue>>

THEOREM Spec => []CountsConsistent
THEOREM Spec => []NoLoss
THEOREM Spec => []MonotonicShrink

=====================================================================================
