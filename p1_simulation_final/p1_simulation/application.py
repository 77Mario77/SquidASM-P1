import ast
import random

from netqasm.sdk import Qubit
from squidasm.sim.stack.program import Program, ProgramContext, ProgramMeta
from squidasm.util.routines import teleport_send, teleport_recv


# Codifica degli stati BB84:
# 0 = |0>, 1 = |1>, 2 = |+>, 3 = |->
ORTHOGONAL = {0: 1, 1: 0, 2: 3, 3: 2}


def abort_limits(num_bits, r):
    """Estremi [low, high] del numero di elementi che si possono ricevere
    dall'altro destinatario senza abortire: L(1/2 - r) <= n <= L(1/2 + r)."""
    low = int(num_bits * (0.5 - r) + 0.999999999)
    high = int(num_bits * (0.5 + r) + 1e-9)
    return low, high


def prepare_bb84(connection, state):
    q = Qubit(connection)
    if state in (1, 3):
        q.X()
    if state in (2, 3):
        q.H()
    return q


def measure_and_exclude(q, connection):
    """Misura in base Z oppure X (scelta a caso) ed esclude uno stato BB84
    (quantum state elimination)."""
    basis_x = random.choice([False, True])
    if basis_x:
        q.H()

    outcome_future = q.measure()
    yield from connection.flush()
    outcome = int(outcome_future)

    if basis_x:
        excluded = 3 if outcome == 0 else 2
    else:
        excluded = 1 if outcome == 0 else 0

    return excluded


class AliceProgram(Program):
    def __init__(self, num_bits=32, message_bit=0, scenario="authentic"):
        if scenario not in ("authentic", "altered", "forgery"):
            raise ValueError(f"Scenario sconosciuto: {scenario}")
        self.num_bits = num_bits
        self.message_bit = message_bit
        self.scenario = scenario

    @property
    def meta(self):
        return ProgramMeta(
            name="p1_alice",
            csockets=["Bob", "Charlie"],
            epr_sockets=["Bob", "Charlie"],
            max_qubits=2,
        )

    def run(self, context: ProgramContext):
        connection = context.connection
        keys = {}

        # Fase di distribuzione (passi 1 e 2 del protocollo): per ogni
        # messaggio k Alice genera la chiave privata e ne manda una copia
        # a Bob e una a Charlie, elemento per elemento.
        for message in (0, 1):
            keys[message] = [random.randrange(4) for _ in range(self.num_bits)]
            for state in keys[message]:
                for peer in ("Bob", "Charlie"):
                    q = prepare_bb84(connection, state)
                    yield from teleport_send(q, context, peer)

        # Aspetta che Bob e Charlie abbiano finito lo scambio dei qubit.
        yield from context.csockets["Bob"].recv()
        yield from context.csockets["Charlie"].recv()

        # Fase di messaggistica: Alice invia (m, PrivKey_m) a Bob.
        declared_key = list(keys[self.message_bit])
        if self.scenario == "altered":
            declared_key = [ORTHOGONAL[x] for x in declared_key]

        context.csockets["Bob"].send(repr((self.message_bit, declared_key)))

        return {
            "message": self.message_bit,
            "scenario": self.scenario,
            "signature_length": self.num_bits,
        }


class RecipientProgram(Program):
    PEER = None    # nome di chi esegue il programma
    OTHER = None   # nome dell'altro destinatario
    IS_BOB = False

    def __init__(self, num_bits=32, sa=0.0, sv=0.05, r=0.1):
        self.num_bits = num_bits
        self.sa = sa
        self.sv = sv
        self.r = r

    @property
    def meta(self):
        return ProgramMeta(
            name=f"p1_{self.PEER.lower()}",
            csockets=["Alice", self.OTHER],
            # serve anche il collegamento quantistico con l'altro destinatario
            # perche' i qubit vengono inoltrati (teletrasporto).
            epr_sockets=["Alice", self.OTHER],
            max_qubits=2,
        )

    def run(self, context: ProgramContext):
        conn = context.connection
        cs_alice = context.csockets["Alice"]
        cs_other = context.csockets[self.OTHER]

        records = []                  # (messaggio, posizione, stato escluso)
        n_sent = {0: 0, 1: 0}         # qubit inoltrati all'altro destinatario
        n_recv = {0: 0, 1: 0}         # qubit ricevuti dall'altro destinatario

        # Passi 2-4: per ogni elemento della firma si riceve il qubit da
        # Alice e si decide a caso se tenerlo (e misurarlo) oppure inoltrarlo.
        # Chi riceve un qubit inoltrato lo misura subito.
        for message in (0, 1):
            for index in range(self.num_bits):
                q = yield from teleport_recv(context, "Alice")

                my_forward = random.choice([True, False])

                # Bob e Charlie si dicono (in modo classico) se stanno
                # inoltrando la posizione corrente, cosi' sanno chi deve
                # teletrasportare e chi ricevere. Il valore del qubit non
                # viene mai comunicato.
                cs_other.send(repr(my_forward))
                other_forward = ast.literal_eval((yield from cs_other.recv()))

                if not my_forward:
                    excluded = yield from measure_and_exclude(q, conn)
                    records.append((message, index, excluded))

                # Ordine fisso per evitare blocchi: prima inoltra Bob,
                # poi Charlie.
                for sender in ("Bob", "Charlie"):
                    forwards = my_forward if sender == self.PEER else other_forward
                    if not forwards:
                        continue
                    if sender == self.PEER:
                        yield from teleport_send(q, context, self.OTHER)
                        n_sent[message] += 1
                    else:
                        q_in = yield from teleport_recv(context, self.OTHER)
                        excluded = yield from measure_and_exclude(q_in, conn)
                        records.append((message, index, excluded))
                        n_recv[message] += 1

        cs_alice.send("READY")

        # Passo 5: controllo sul numero di qubit ricevuti dall'altro.
        low, high = abort_limits(self.num_bits, self.r)
        local_abort = any(not (low <= n_recv[m] <= high) for m in (0, 1))

        cs_other.send(repr(local_abort))
        peer_abort = ast.literal_eval((yield from cs_other.recv()))
        protocol_abort = bool(local_abort or peer_abort)

        if self.IS_BOB:
            return (yield from self._bob_messaging(
                context, records, n_sent, n_recv, protocol_abort
            ))
        return (yield from self._charlie_messaging(
            context, records, n_sent, n_recv, protocol_abort
        ))

    
    def _count_mismatches(self, records, message, declared_key):
        """Un mismatch e' un elemento in cui lo stato dichiarato coincide con
        lo stato che il destinatario aveva escluso."""
        return sum(
            1 for m, i, excluded in records
            if m == message and excluded == declared_key[i]
        )

    def _forge(self, records, true_message):
        """Bob prova a firmare il messaggio opposto. Per le posizioni di cui
        ha un record scarta lo stato escluso e sceglie a caso tra gli altri
        tre; per le altre indovina a caso."""
        fake_message = 1 - true_message
        known = {i: e for m, i, e in records if m == fake_message}
        fake_key = []
        for i in range(self.num_bits):
            if i in known:
                fake_key.append(random.choice([s for s in range(4) if s != known[i]]))
            else:
                fake_key.append(random.randrange(4))
        return fake_message, fake_key

    def _bob_messaging(self, context, records, n_sent, n_recv, protocol_abort):
        message, declared_key = ast.literal_eval(
            (yield from context.csockets["Alice"].recv())
        )

        mismatches = self._count_mismatches(records, message, declared_key)
        # Il paper dice "meno di s_a L mismatch"; con s_a = 0 (caso ideale)
        # si accetta se non ce ne sono, quindi qui si usa <=.
        accepted = (not protocol_abort) and mismatches <= int(self.sa * self.num_bits)

        forwarded_message = message
        forwarded_key = list(declared_key)
        if getattr(self, "forge", False):
            forwarded_message, forwarded_key = self._forge(records, message)

        context.csockets[self.OTHER].send(
            repr((forwarded_message, forwarded_key, accepted, mismatches, protocol_abort))
        )

        return {
            "recipient": "Bob",
            "message": message,
            "mismatches": mismatches,
            "accepted": accepted,
            "records_checked": sum(1 for m, _, _ in records if m == message),
            "n_recv": [n_recv[0], n_recv[1]],
            "n_sent": [n_sent[0], n_sent[1]],
            "aborted": protocol_abort,
            "forgery_attempt": getattr(self, "forge", False),
            "forwarded_message": forwarded_message,
        }

    def _charlie_messaging(self, context, records, n_sent, n_recv, protocol_abort):
        (
            message,
            declared_key,
            bob_accepted,
            bob_mismatches,
            bob_abort,
        ) = ast.literal_eval((yield from context.csockets[self.OTHER].recv()))

        mismatches = self._count_mismatches(records, message, declared_key)
        protocol_abort = protocol_abort or bool(bob_abort)
        accepted = (not protocol_abort) and mismatches <= int(self.sv * self.num_bits)

        return {
            "recipient": "Charlie",
            "message": message,
            "mismatches": mismatches,
            "accepted": accepted,
            "bob_accepted": bob_accepted,
            "bob_mismatches": bob_mismatches,
            "records_checked": sum(1 for m, _, _ in records if m == message),
            "n_recv": [n_recv[0], n_recv[1]],
            "n_sent": [n_sent[0], n_sent[1]],
            "aborted": protocol_abort,
        }


class BobProgram(RecipientProgram):
    PEER = "Bob"
    OTHER = "Charlie"
    IS_BOB = True

    def __init__(self, *args, forge=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.forge = forge


class CharlieProgram(RecipientProgram):
    PEER = "Charlie"
    OTHER = "Bob"
    IS_BOB = False
