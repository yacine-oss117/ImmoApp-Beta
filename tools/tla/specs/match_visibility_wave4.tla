----------------------------- MODULE match_visibility_wave4 -----------------------------
EXTENDS TLC

(*
Wave-4: Matching visibility correctness.
We model stored pairs (cache), candidate edges, and the "visible" pairs that
the API returns after applying ACTIVE predicates.

Invariants:
  - pairs ⊆ candidates ⊆ compat
  - visible pairs are always active and compatible
  - when only active sets shrink, visible pairs cannot increase
*)

CONSTANTS Demandes, Offers, Compat

VARIABLES activeD, activeO, candidates, pairs

Init ==
    /\ activeD \subseteq Demandes
    /\ activeO \subseteq Offers
    /\ candidates \subseteq Compat
    /\ pairs \subseteq candidates

VisiblePairs ==
    {p \in pairs: p[1] \in activeD /\ p[2] \in activeO}

DeactivateDemande(d) ==
    /\ d \in activeD
    /\ activeD' = activeD \ {d}
    /\ activeO' = activeO
    /\ candidates' = candidates
    /\ pairs' = pairs

DeactivateOffer(o) ==
    /\ o \in activeO
    /\ activeO' = activeO \ {o}
    /\ activeD' = activeD
    /\ candidates' = candidates
    /\ pairs' = pairs

RebuildCandidates ==
    /\ candidates' \subseteq Compat
    /\ activeD' = activeD
    /\ activeO' = activeO
    /\ pairs' = pairs

RebuildPairs ==
    /\ pairs' \subseteq candidates
    /\ candidates' = candidates
    /\ activeD' = activeD
    /\ activeO' = activeO

Next ==
    \E d \in activeD : DeactivateDemande(d)
    \/ \E o \in activeO : DeactivateOffer(o)
    \/ RebuildCandidates
    \/ RebuildPairs

Inv ==
    /\ candidates \subseteq Compat
    /\ pairs \subseteq candidates
    /\ \A p \in VisiblePairs : p \in Compat

MonotonicStep ==
    (/\ activeD' \subseteq activeD
     /\ activeO' \subseteq activeO
     /\ candidates' = candidates
     /\ pairs' = pairs)
    => VisiblePairs' \subseteq VisiblePairs

Spec ==
    Init /\ [][Next]_<<activeD, activeO, candidates, pairs>>

THEOREM Spec => []Inv
THEOREM Spec => []MonotonicStep

=====================================================================================
