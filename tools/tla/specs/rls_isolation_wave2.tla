------------------------------ MODULE rls_isolation_wave2 ------------------------------
EXTENDS Naturals, Sequences

CONSTANTS AGENCIES, ROWS

VARIABLES owner, visible

Init ==
    /\ owner = [r \in ROWS |-> CHOOSE a \in AGENCIES : TRUE]
    /\ visible = [a \in AGENCIES |-> { r \in ROWS : owner[r] = a }]

ReadAllowed(a, r) ==
    /\ a \in AGENCIES
    /\ r \in ROWS
    /\ r \in visible[a]

WriteAllowed(a, r) ==
    /\ a \in AGENCIES
    /\ r \in ROWS
    /\ owner[r] = a

Next ==
    \E a \in AGENCIES, r \in ROWS :
        ReadAllowed(a, r) \/ WriteAllowed(a, r)

Isolation ==
    \A a \in AGENCIES, r \in ROWS :
        (owner[r] # a) => ~(r \in visible[a])

Spec ==
    Init /\ [][Next]_<<owner, visible>>

==============================================================================
