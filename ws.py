"""
WEBSOCKET MÍNIMO (só biblioteca padrão do Python, nada para instalar).

É usado pelo jogo.py (cliente) e pelo servidor.py. Com WebSocket o jogo
passa pela porta 443 (a mesma dos sites seguros), que redes de faculdade e
empresas quase sempre deixam passar, e pode ficar em hospedagens gratuitas.
"""
import base64
import hashlib
import os
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXTO, OP_BIN, OP_FECHAR, OP_PING, OP_PONG = 0, 1, 2, 8, 9, 10

LIMITE_QUADRO = 2_000_000       # protege contra quadros gigantes


def chave_aceite(chave):
    """Valor que o servidor devolve em Sec-WebSocket-Accept."""
    return base64.b64encode(
        hashlib.sha1((chave + GUID).encode()).digest()).decode()


def nova_chave():
    return base64.b64encode(os.urandom(16)).decode()


def construir_quadro(payload, opcode=OP_TEXTO, mascarar=False):
    """Monta um quadro WebSocket. O CLIENTE precisa mascarar; o servidor não."""
    n = len(payload)
    b0 = 0x80 | opcode                      # FIN + opcode
    mbit = 0x80 if mascarar else 0

    if n < 126:
        cab = bytes([b0, mbit | n])
    elif n < 65536:
        cab = bytes([b0, mbit | 126]) + struct.pack(">H", n)
    else:
        cab = bytes([b0, mbit | 127]) + struct.pack(">Q", n)

    if not mascarar:
        return cab + payload

    chave = os.urandom(4)
    return cab + chave + _xor(payload, chave)


def _xor(dados, chave):
    if not dados:
        return b""
    # truque rápido: XOR com a chave repetida, feito como número inteiro
    rep = (chave * (len(dados) // 4 + 1))[:len(dados)]
    return (int.from_bytes(dados, "big") ^ int.from_bytes(rep, "big")).to_bytes(
        len(dados), "big")


class LeitorQuadros:
    """Lê mensagens WebSocket de uma função receber(n) -> bytes.
    receber devolve b"" quando a conexão fecha."""

    def __init__(self, receber, inicial=b""):
        self.receber = receber
        self.buf = bytearray(inicial)
        self._op = None
        self._partes = []

    def _ler(self, n):
        while len(self.buf) < n:
            parte = self.receber(65536)
            if not parte:
                raise EOFError("conexão fechada")
            self.buf += parte
        dados = bytes(self.buf[:n])
        del self.buf[:n]
        return dados

    def proximo(self):
        """Devolve (opcode, payload) de uma mensagem completa.
        Levanta EOFError se a conexão fechou."""
        while True:
            b0, b1 = self._ler(2)
            fin, op = b0 & 0x80, b0 & 0x0F
            mascara, n = b1 & 0x80, b1 & 0x7F

            if n == 126:
                n = struct.unpack(">H", self._ler(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._ler(8))[0]
            if n > LIMITE_QUADRO:
                raise ValueError("quadro grande demais")

            chave = self._ler(4) if mascara else None
            dados = self._ler(n) if n else b""
            if chave:
                dados = _xor(dados, chave)

            if op >= 8:                      # ping, pong, fechar (não fragmentam)
                return op, dados

            if op != OP_CONT:
                self._op, self._partes = op, []
            self._partes.append(dados)

            if fin:
                msg = b"".join(self._partes)
                op_final = self._op if self._op is not None else OP_TEXTO
                self._op, self._partes = None, []
                return op_final, msg
