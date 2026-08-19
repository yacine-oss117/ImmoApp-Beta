------------------------------ MODULE row_version_wave2 ------------------------------
EXTENDS Naturals

CONSTANTS ROWS

VARIABLES version

Init ==
    /\ version = [r \in ROWS |-> 1]

Write(r, expected) ==
    /\ r \in ROWS
    /\ expected = version[r]
    /\ version' = [version EXCEPT ![r] = @ + 1]

Reject(r, expected) ==
    /\ r \in ROWS
    /\ expected # version[r]
    /\ version' = version

Next ==
    \E r \in ROWS, expected \in 1..5 :
        Write(r, expected) \/ Reject(r, expected)

NoStaleOverwrite ==
    \A r \in ROWS :
        version[r] >= 1

Spec ==
    Init /\ [][Next]_<<version>>

==============================================================================
