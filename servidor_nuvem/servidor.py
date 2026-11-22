"""
SERVIDOR DO JOGO - Tecnologia Fora de Controle

Precisa só do mundo.py na mesma pasta. Não precisa instalar nada.

TRÊS JEITOS DE USAR
  1) Rede local (casa, laboratório que permita):  python servidor.py
     Jogadores entram com  IP:5555  (ex.: 192.168.0.10:5555)
  2) Internet / faculdade (RECOMENDADO): suba este servidor numa hospedagem
     (veja o GUIA_FACULDADE.md). O jogo conecta por WebSocket seguro
     (porta 443), que redes de faculdade deixam passar.
     A hospedagem define a variável PORT; o servidor usa ela sozinho.
  3) Teste no próprio PC: python servidor.py  e entre com  ws://localhost:8080

Opções:  --mundo 3   começa direto no mundo 3 (para testar)
         --ws 9000   muda a porta do WebSocket

O servidor controla os ROBÔS (movimento, ataques, vida), os projéteis
deles e a vida dos jogadores, assim todos veem exatamente a mesma coisa.

Protocolo: uma mensagem JSON por linha, por TCP direto ou dentro de
quadros WebSocket.
"""
import json
import math
import os
import random
import socket
import struct
import sys
import threading
import time

# >>> WS_EMBUTIDO
# WebSocket (só biblioteca padrão), embutido aqui para NÃO precisar de arquivo extra.
import base64, hashlib, struct      # (também avisam o PyInstaller que são usados)
import types

_WS_FONTE = r'''
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
'''
ws = types.ModuleType("ws")
exec(_WS_FONTE, ws.__dict__)
# <<< WS_EMBUTIDO

from mundo import (
    CHAO_Y, LARGURA_MUNDO, JOGADOR_LARG, JOGADOR_ALT,
    VIDA_JOGADOR, INVUL_MS, TEMPO_RENASCER_MS,
    DANO_JOGADOR, CURA_DEVORAR, LENTO_TEIA_MS,
    TIPOS_INIMIGO, STATS_INIMIGO, VISAO_Y,
    FASES, PORTAL_LARG, PORTAL_ALT, TEMPO_CONTAGEM_PORTAL_MS,
    TEMPO_TRANSICAO_MS, zonas_inimigos, stats_inimigo, esc,
    CHEFE, BOSS_ID, TEMPO_REINICIO_CHEFE_MS, largura_do_mundo,
)

HOST = "0.0.0.0"
PORTA = 5555                                        # TCP direto (rede local)
PORTA_WS = int(os.environ.get("PORT", 8080))        # WebSocket (internet/nuvem);
                                                    # a hospedagem define PORT
MAX_JOGADORES = int(os.environ.get("MAX_JOGADORES", 8))
TAXA = int(os.environ.get("TAXA", 30))              # atualizações do mundo por segundo
                                                    # (na nuvem grátis, 20 pesa menos)
TOTAL_CLASSES = 5    # precisa bater com a lista CLASSES do jogo.py

clientes = {}        # id -> dados do jogador
inimigos = {}        # id -> Inimigo
projeteis = []       # projéteis dos robôs
ultimo_acerto = {}   # (jogador, robô, tipo) -> instante do último acerto
trava = threading.Lock()
proximo_id = 1
proximo_proj = 1
proximo_inimigo = 1

fase_atual = 0          # índice em FASES
portal_aberto = False
contagem_ate = None     # instante em que a troca de mundo acontece
pausa_ate = 0           # durante a troca de mundo o jogo fica "congelado"

ondas = []              # ondas de choque do chefe
proximo_onda = 1
zonas = []              # áreas de golpe (soco dos robôs, pisão do chefe), duram uns 0,2 s
proximo_zona = 1
media_tick_ms = 1000.0 / 30       # tempo REAL entre atualizações do mundo (para diagnóstico)
media_trabalho_ms = 0.0           # quanto o servidor gasta calculando cada uma

# Dano nos jogadores: quem decide se foi atingido é o COMPUTADOR DE QUEM LEVA O GOLPE
# (o que aparece na tela dele é o que vale). O servidor só confere se faz sentido.
TOLERANCIA_ATRASO_S = 0.7
chefe = None            # o Nexus, quando a batalha começa
chefe_derrotado = False
eventos = []            # avisos para todos (ex.: chefe morreu)


def agora_ms():
    return int(time.monotonic() * 1000)


def largura_atual():
    return largura_do_mundo(fase_atual)


def codificar(msg):
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode()


def enviar(cliente, msg):
    try:
        with cliente["envio"]:
            cliente["conn"].sendall(codificar(msg))
        return True
    except OSError:
        return False


def numero(valor, padrao=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def sobrepoe(a, b):
    """a e b = (x, y, largura, altura)"""
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
            and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])


def retangulo_jogador(c):
    return (c["x"], c["y"], JOGADOR_LARG, JOGADOR_ALT)


# ---------------------------------------------------------
# DANO NOS JOGADORES
# ---------------------------------------------------------
def dano_jogador(c, dano, agora):
    if c["hp"] <= 0 or agora < c["invul_ate"]:
        return
    c["hp"] = max(0, c["hp"] - dano)
    c["invul_ate"] = agora + INVUL_MS
    if c["hp"] == 0:
        c["morto_ate"] = agora + TEMPO_RENASCER_MS
        print(f"[x] {c['nome']} foi derrotado")


# ---------------------------------------------------------
# ROBÔS
# ---------------------------------------------------------
def criar_zona(x, y, w, h, dano, agora, duracao=220):
    """Área de golpe que existe por um instante. Cada jogador confere sozinho
    se estava dentro dela e avisa o servidor."""
    global proximo_zona
    zonas.append({"id": proximo_zona, "x": x, "y": y, "w": w, "h": h,
                  "dano": dano, "fim": agora + duracao,        # some da tela
                  "valido": agora + duracao + 600,             # ainda aceita avisos (atraso da internet)
                  "feridos": set()})
    proximo_zona += 1


def atualizar_zonas(agora):
    for z in zonas[:]:
        if agora > z["valido"]:
            zonas.remove(z)


class Inimigo:
    def __init__(self, iid, tipo, zmin, zmax, fase=0, altura=0):
        self.id = iid
        self.tipo = tipo
        self.idx = TIPOS_INIMIGO.index(tipo)
        self.st = stats_inimigo(tipo, fase)      # já com a dificuldade do mundo
        self.altura = altura                      # > 0: em cima de uma plataforma
        self.zmin = zmin
        self.zmax = zmax
        self.reset()

    def reset(self):
        st = self.st
        self.vivo = True
        self.hp = st["hp"]
        self.x = random.uniform(self.zmin, self.zmax)
        if st["voa"]:
            self.base = CHAO_Y - st["y_voo"]
        else:
            self.base = CHAO_Y - self.altura
        self.y = self.base
        self.d = random.choice((-1, 1))
        self.an = 0                 # 0 parado, 1 andando, 2 atacando
        self.acao_em = None
        self.fim_ataque = 0
        self.prox_ataque = 0
        self.lento_ate = 0
        self.pausa_ate = 0

    # ----- percepção -----
    def escolher_alvo(self, vivos):
        st = self.st
        melhor, menor = None, 1e18
        cy = self.y - st["alt"] / 2

        for c in vivos:
            dx = (c["x"] + JOGADOR_LARG / 2) - self.x
            dy = (c["y"] + JOGADOR_ALT / 2) - cy

            if abs(dx) > st["visao"]:
                continue
            if not st["voa"] and abs(dy) > VISAO_Y:
                continue
            if abs(dx) < menor:
                menor, melhor = abs(dx), (c, dx, dy)

        return melhor

    # ----- ataque -----
    def iniciar_ataque(self, agora, fator):
        st = self.st
        self.an = 2
        self.acao_em = agora + st["windup"] / fator
        self.fim_ataque = self.acao_em + st["recover"]
        self.prox_ataque = agora + st["intervalo"] / fator

    def executar(self, agora, vivos):
        global proximo_proj
        st = self.st

        if st["ataque"] == "soco":
            if self.d > 0:
                x0 = self.x + st["larg"] / 2
            else:
                x0 = self.x - st["larg"] / 2 - st["golpe_larg"]
            criar_zona(x0, self.y - st["alt"], st["golpe_larg"], st["alt"],
                       st["dano"], agora)
            return

        ox = self.x + self.d * st["larg"] / 2
        oy = self.y - st["alt"] * st["muzzle"]
        vel = st["proj_vel"]
        vx, vy = self.d * vel, 0.0

        if st["mira"]:                        # drone: mira em você
            alvo = self.escolher_alvo(vivos)
            if alvo:
                c = alvo[0]
                tx = c["x"] + JOGADOR_LARG / 2
                ty = c["y"] + JOGADOR_ALT / 2
                ang = math.atan2(ty - oy, tx - ox)
                vx, vy = math.cos(ang) * vel, math.sin(ang) * vel

        projeteis.append({
            "id": proximo_proj, "x": ox, "y": oy, "vx": vx, "vy": vy,
            "tipo": self.idx, "dano": st["dano"], "r": st["proj_raio"],
            "fim": agora + st["proj_vida"],
        })
        proximo_proj += 1

    # ----- um passo da simulação -----
    def atualizar(self, agora, dt, vivos):
        st = self.st

        if not self.vivo:          # robô derrotado não nasce de novo
            return

        if st["voa"]:
            self.y = self.base + 8 * math.sin(agora / 400 + self.id)

        # Atacando: fica parado até o golpe acontecer
        if self.an == 2:
            if self.acao_em is not None and agora >= self.acao_em:
                self.acao_em = None
                self.executar(agora, vivos)
            if agora < self.fim_ataque:
                return
            self.an = 0

        fator = 0.5 if agora < self.lento_ate else 1.0
        alvo = self.escolher_alvo(vivos)
        pode_atacar = agora >= self.prox_ataque
        mover = 0.0

        if alvo:
            c, dx, dy = alvo
            self.d = 1 if dx >= 0 else -1
            dist = abs(dx)

            if st["ataque"] == "soco":
                alcance = st["larg"] / 2 + JOGADOR_LARG / 2 + st["alcance"]
                if dist <= alcance and abs(dy) <= esc(80) and pode_atacar:
                    self.iniciar_ataque(agora, fator)
                    return
                if dist > alcance * 0.8:
                    mover = self.d * st["vel_persegue"]
            else:
                # tiro reto só se o alvo estiver mais ou menos na mesma altura
                na_mira = st["mira"] or abs(dy) <= esc(120)
                if dist <= st["alcance"] and na_mira and pode_atacar:
                    self.iniciar_ataque(agora, fator)
                    return
                if dist > st["alcance"] * 0.75:
                    mover = self.d * st["vel_persegue"]
                elif dist < st["alcance"] * 0.3:
                    mover = -self.d * st["vel"]          # recua um pouco
        else:
            if agora >= self.pausa_ate:
                mover = self.d * st["vel"]

        nx = self.x + mover * fator * dt
        bateu = False

        if nx <= self.zmin:
            nx, bateu = self.zmin, True
        elif nx >= self.zmax:
            nx, bateu = self.zmax, True

        if bateu and not alvo:                    # patrulha: vira e espera
            self.d = -self.d
            self.pausa_ate = agora + random.randint(500, 1400)

        self.an = 1 if abs(nx - self.x) > 0.01 else 0
        self.x = nx


def atualizar_projeteis(agora, dt, vivos):
    for p in projeteis[:]:
        p["x"] += p["vx"] * dt
        p["y"] += p["vy"] * dt
        r = p["r"]

        if (agora > p["fim"] or p["x"] < -100
                or p["x"] > largura_atual() + 100 or p["y"] >= CHAO_Y):
            projeteis.remove(p)
            continue


def criar_inimigos(fase):
    global proximo_inimigo
    inimigos.clear()
    projeteis.clear()
    for tipo, zmin, zmax, altura in zonas_inimigos(fase):
        inimigos[proximo_inimigo] = Inimigo(proximo_inimigo, tipo, zmin, zmax,
                                            fase, altura)
        proximo_inimigo += 1


# ---------------------------------------------------------
# CHEFE: NEXUS
# ---------------------------------------------------------
def distancia_ponto_segmento(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    comp2 = dx * dx + dy * dy
    t = 0.0 if comp2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / comp2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def criar_onda(x, sentido, agora):
    global proximo_onda
    sj = CHEFE["salto"]
    ondas.append({"id": proximo_onda, "x": float(x), "vx": sentido * sj["onda_vel"],
                  "fim": agora + sj["onda_vida"], "dano": sj["dano"]})
    proximo_onda += 1


def atualizar_ondas(agora, dt, vivos):
    sj = CHEFE["salto"]
    for o in ondas[:]:
        o["x"] += o["vx"] * dt
        if agora > o["fim"] or o["x"] < 0 or o["x"] > largura_atual():
            ondas.remove(o)
            continue


class Chefe:
    """O Nexus. Estados: nascendo, livre, salto, pouso, disparo, laser."""

    def __init__(self, agora, n_jogadores):
        c = CHEFE
        f = FASES[fase_atual]
        self.alt = STATS_INIMIGO["nexus"]["alt"]
        self.hp_max = int(c["hp"] * (1 + c["hp_extra"] * max(0, n_jogadores - 1)))
        self.hp = self.hp_max
        self.x = float(f["nexus_x"])
        self.y = float(CHAO_Y)
        self.d = -1
        self.vivo = True
        self.vulneravel = False           # invulnerável enquanto sai do chão
        self.estado = "nascendo"
        self.an = 3
        self.fim_estado = agora + c["nascer_ms"]
        self.prox_ataque = 0
        self.ultimo = None
        self.salto = None
        self.laser = None
        self.pendentes = []
        self.n_tiros = 0
        self.disparados = 0
        self.t_carga = self.t_fim_laser = 0
        self.arena_min = max(esc(250), f["nexus_x"] - esc(800))
        self.arena_max = min(largura_atual() - esc(150), f["nexus_x"] + esc(200))

    def fase(self):
        fr = self.hp / self.hp_max
        a, b = CHEFE["fases"]
        return 0 if fr > a else (1 if fr > b else 2)

    def alvo(self, vivos):
        melhor, menor = None, 1e18
        for c in vivos:
            dist = abs(c["x"] + JOGADOR_LARG / 2 - self.x)
            if dist < menor:
                menor, melhor = dist, c
        return melhor

    def voltar_livre(self, agora):
        self.estado = "livre"
        self.an = 0
        self.laser = None
        self.prox_ataque = agora + CHEFE["pausa"][self.fase()]

    # ----- movimento e escolha do ataque -----
    def mover(self, dt, alvo):
        if not alvo:
            self.an = 0
            return
        dx = alvo["x"] + JOGADOR_LARG / 2 - self.x
        self.d = 1 if dx >= 0 else -1
        if abs(dx) > CHEFE["dist_ideal"]:
            vel = CHEFE["vel"] * (1 + 0.25 * self.fase())
            self.x = max(self.arena_min, min(self.arena_max, self.x + self.d * vel * dt))
            self.an = 1
        else:
            self.an = 0

    def escolher(self, agora, alvo):
        perto = abs(alvo["x"] + JOGADOR_LARG / 2 - self.x) < CHEFE["alcance_perto"]
        pesos = ({"salto": 50, "disparo": 25, "laser": 25} if perto
                 else {"salto": 25, "disparo": 45, "laser": 30})
        if self.ultimo in pesos:
            pesos[self.ultimo] *= 0.25            # evita repetir o mesmo ataque
        ataque = random.choices(list(pesos), weights=list(pesos.values()))[0]
        self.ultimo = ataque
        getattr(self, "iniciar_" + ataque)(agora, alvo)

    # ----- 1) salto + onda no chão -----
    def iniciar_salto(self, agora, alvo):
        sj = CHEFE["salto"]
        cx = alvo["x"] + JOGADOR_LARG / 2
        alvo_x = max(self.arena_min, min(self.arena_max, cx))
        dist = max(-sj["alcance"], min(sj["alcance"], alvo_x - self.x))
        self.d = 1 if dist >= 0 else -1
        self.salto = {"t0": agora, "x0": self.x, "x1": self.x + dist}
        self.estado, self.an = "salto", 4

    def passo_salto(self, agora, vivos):
        sj = CHEFE["salto"]
        s = self.salto
        u = (agora - s["t0"]) / sj["dur"]

        if u < 1:
            self.x = s["x0"] + (s["x1"] - s["x0"]) * u
            self.y = CHAO_Y - 4 * sj["alt_arco"] * u * (1 - u)
            return

        self.x, self.y = s["x1"], float(CHAO_Y)
        self.estado, self.an = "pouso", 5
        self.fim_estado = agora + sj["pouso_ms"]

        # pisão: área embaixo dele (quem estiver pulando alto escapa)
        criar_zona(self.x - sj["raio_pisao"], CHAO_Y - esc(40),
                   2 * sj["raio_pisao"], esc(40), sj["dano_pisao"], agora)

        criar_onda(self.x, -1, agora)
        criar_onda(self.x, 1, agora)

    # ----- 2) rajada de plasma -----
    def iniciar_disparo(self, agora, alvo):
        dj = CHEFE["disparo"]
        self.n_tiros = dj["n"][self.fase()]
        self.disparados = 0
        self.pendentes = [agora + dj["preparo"] + i * dj["intervalo_tiro"]
                          for i in range(self.n_tiros)]
        self.fim_estado = self.pendentes[-1] + dj["recupera"]
        self.d = 1 if alvo["x"] + JOGADOR_LARG / 2 >= self.x else -1
        self.estado, self.an = "disparo", 6

    def atirar(self, alvo, agora):
        global proximo_proj
        dj = CHEFE["disparo"]
        ox = self.x + self.d * esc(45)
        oy = self.y - self.alt * 0.6

        if alvo:
            ang = math.atan2(alvo["y"] + JOGADOR_ALT / 2 - oy,
                             alvo["x"] + JOGADOR_LARG / 2 - ox)
        else:
            ang = 0.0 if self.d > 0 else math.pi

        ang += (self.disparados - (self.n_tiros - 1) / 2) * math.radians(dj["espalha"])
        projeteis.append({
            "id": proximo_proj, "x": ox, "y": oy,
            "vx": math.cos(ang) * dj["vel"], "vy": math.sin(ang) * dj["vel"],
            "tipo": TIPOS_BOSS_IDX, "dano": dj["dano"], "r": dj["raio"],
            "fim": agora + dj["vida"],
        })
        proximo_proj += 1

    def passo_disparo(self, agora, vivos):
        while self.pendentes and agora >= self.pendentes[0]:
            self.pendentes.pop(0)
            self.atirar(self.alvo(vivos), agora)
            self.disparados += 1
        if not self.pendentes and agora >= self.fim_estado:
            self.voltar_livre(agora)

    # ----- 3) laser contínuo do peito -----
    def iniciar_laser(self, agora, alvo):
        lj = CHEFE["laser"]
        self.d = 1 if alvo["x"] + JOGADOR_LARG / 2 >= self.x else -1
        self.t_carga = agora + lj["preparo"]
        self.t_fim_laser = self.t_carga + lj["dur"]
        self.laser = {"on": 2, "ang": lj["angulo_ini"]}
        self.estado, self.an = "laser", 7

    def segmento_laser(self, ang):
        lj = CHEFE["laser"]
        ox = self.x + self.d * esc(40)
        oy = self.y - self.alt * 0.58
        rad = math.radians(ang)
        dx, dy = self.d * math.cos(rad), -math.sin(rad)      # y cresce para baixo
        comp = lj["comprimento"]
        if dy > 0:                                           # apontando p/ baixo: para no chão
            comp = min(comp, (CHAO_Y - oy) / dy)
        return ox, oy, ox + dx * comp, oy + dy * comp, comp

    def passo_laser(self, agora, vivos):
        lj = CHEFE["laser"]

        if agora < self.t_carga:                             # carregando (aviso)
            self.laser = {"on": 2, "ang": lj["angulo_ini"]}
        elif agora < self.t_fim_laser:                       # disparando
            u = (agora - self.t_carga) / lj["dur"]
            ang = lj["angulo_ini"] + (lj["angulo_fim"] - lj["angulo_ini"]) * u
            self.laser = {"on": 1, "ang": ang}
        else:
            self.laser = None
            self.estado, self.an = "pouso", 0
            self.fim_estado = agora + lj["recupera"]

    def info_laser(self):
        if not self.laser:
            return None
        ox, oy, _, _, comp = self.segmento_laser(self.laser["ang"])
        return [self.laser["on"], int(ox), int(oy), int(self.laser["ang"]),
                int(comp), self.d]

    # ----- um passo -----
    def atualizar(self, agora, dt, vivos):
        if self.estado == "nascendo":
            if agora >= self.fim_estado:
                self.estado, self.an = "livre", 0
                self.vulneravel = True
                self.prox_ataque = agora + 1200
            return

        if self.estado == "livre":
            alvo = self.alvo(vivos)
            self.mover(dt, alvo)
            if alvo and agora >= self.prox_ataque:
                self.escolher(agora, alvo)
        elif self.estado == "salto":
            self.passo_salto(agora, vivos)
        elif self.estado == "pouso":
            if agora >= self.fim_estado:
                self.y = float(CHAO_Y)
                self.voltar_livre(agora)
        elif self.estado == "disparo":
            self.passo_disparo(agora, vivos)
        elif self.estado == "laser":
            self.passo_laser(agora, vivos)


TIPOS_BOSS_IDX = TIPOS_INIMIGO.index("nexus")


def iniciar_chefe(agora):
    """Um jogador terminou a conversa com o Nexus: a batalha começa."""
    global chefe
    if not FASES[fase_atual].get("chefe") or chefe is not None or chefe_derrotado:
        return
    n = sum(1 for c in clientes.values() if c["entrou"])
    chefe = Chefe(agora, n)
    print(f"[!] O NEXUS desperta! ({n} jogador(es), vida {chefe.hp_max})")


def reviver_todos(agora, invul_ms):
    for c in clientes.values():
        if c["entrou"]:
            c["hp"] = VIDA_JOGADOR
            c["invul_ate"] = agora + invul_ms
            c["x"], c["y"] = esc(80), CHAO_Y - JOGADOR_ALT


def matar_chefe(agora):
    global chefe_derrotado
    chefe.vivo = False
    chefe.laser = None
    chefe_derrotado = True
    projeteis.clear()
    ondas.clear()
    zonas.clear()
    for c in clientes.values():                   # quem caiu volta para a conversa final
        if c["entrou"] and c["hp"] <= 0:
            c["hp"] = VIDA_JOGADOR
            c["invul_ate"] = agora + 3000
    eventos.append({"t": "boss_morto"})
    print("[*] O NEXUS foi derrotado!")


def reiniciar_chefe(agora):
    """Todos os jogadores caíram: a fase recomeça (e precisa de nova conversa)."""
    global chefe, chefe_derrotado, pausa_ate
    chefe = None
    chefe_derrotado = False
    projeteis.clear()
    ondas.clear()
    zonas.clear()
    pausa_ate = agora + TEMPO_REINICIO_CHEFE_MS
    reviver_todos(agora, TEMPO_REINICIO_CHEFE_MS + 1500)
    print("[x] Todos caíram: a batalha recomeça")
    return {"t": "fase", "n": fase_atual, "fim": False, "reinicio": True,
            "nome": FASES[fase_atual]["nome"]}


def verificar_derrota_chefe(agora):
    if not (chefe and chefe.vivo):
        return None
    em_jogo = [c for c in clientes.values() if c["entrou"]]
    if em_jogo and all(c["hp"] <= 0 for c in em_jogo):
        return reiniciar_chefe(agora)
    return None


# ---------------------------------------------------------
# PORTAL / TROCA DE MUNDO
# ---------------------------------------------------------
def contar_no_portal():
    """(jogadores vivos dentro do portal, jogadores em jogo)"""
    cx = esc(FASES[fase_atual]["portal_x"])
    area = (cx - PORTAL_LARG / 2, CHAO_Y - PORTAL_ALT, PORTAL_LARG, PORTAL_ALT)
    em_jogo = [c for c in clientes.values() if c["entrou"]]
    dentro = [c for c in em_jogo
              if c["hp"] > 0 and sobrepoe(area, retangulo_jogador(c))]
    return len(dentro), len(em_jogo)


def avancar_fase(agora):
    global fase_atual, portal_aberto, contagem_ate, pausa_ate
    global chefe, chefe_derrotado

    proxima = (fase_atual + 1) % len(FASES)
    fim = proxima == 0

    fase_atual = proxima
    portal_aberto = False
    contagem_ate = None
    pausa_ate = agora + TEMPO_TRANSICAO_MS
    chefe, chefe_derrotado = None, False
    ondas.clear()
    zonas.clear()
    criar_inimigos(fase_atual)

    for c in clientes.values():
        if c["entrou"]:
            c["hp"] = VIDA_JOGADOR
            c["invul_ate"] = agora + TEMPO_TRANSICAO_MS + 1500
            c["x"], c["y"] = esc(80), CHAO_Y - JOGADOR_ALT

    print(f"[>] Todos no portal! Indo para {FASES[fase_atual]['nome']}")
    return {"t": "fase", "n": fase_atual, "fim": fim,
            "nome": FASES[fase_atual]["nome"]}


def atualizar_portal(agora):
    """Abre o portal quando todos os robôs morrem e troca de mundo quando
    TODOS os jogadores estão dentro dele. Devolve a mensagem de troca ou None."""
    global portal_aberto, contagem_ate

    if not portal_aberto:
        if inimigos and all(not e.vivo for e in inimigos.values()):
            portal_aberto = True
            print("[!] Todos os robôs derrotados: portal aberto!")
        return None

    dentro, total = contar_no_portal()

    if total > 0 and dentro == total:
        if contagem_ate is None:
            contagem_ate = agora + TEMPO_CONTAGEM_PORTAL_MS
        elif agora >= contagem_ate:
            return avancar_fase(agora)
    else:
        contagem_ate = None

    return None


# ---------------------------------------------------------
# MENSAGENS DOS JOGADORES
# ---------------------------------------------------------
def aplicar_acerto_chefe(cid, cliente, msg):
    if (chefe is None or not chefe.vivo or not chefe.vulneravel
            or cliente["hp"] <= 0):
        return

    agora = agora_ms()
    if abs(cliente["x"] + JOGADOR_LARG / 2 - chefe.x) > esc(1000):
        return

    chave = (cid, BOSS_ID, "melee" if msg.get("v") == "melee" else "proj")
    if agora - ultimo_acerto.get(chave, 0) < 250:
        return
    ultimo_acerto[chave] = agora

    chefe.hp -= DANO_JOGADOR.get(cliente["classe"], 20)
    if chefe.hp <= 0:
        matar_chefe(agora)


def aplicar_acerto(cid, cliente, msg):
    """O jogador diz que acertou um robô. (chamar com a trava)"""
    if numero(msg.get("e"), -1) == BOSS_ID:
        aplicar_acerto_chefe(cid, cliente, msg)
        return

    inimigo = inimigos.get(numero(msg.get("e"), -1))
    if inimigo is None or not inimigo.vivo or cliente["hp"] <= 0:
        return

    agora = agora_ms()
    if abs(cliente["x"] + JOGADOR_LARG / 2 - inimigo.x) > esc(900):
        return                                    # longe demais: ignora

    tipo_golpe = "melee" if msg.get("v") == "melee" else "proj"
    chave = (cid, inimigo.id, tipo_golpe)
    if agora - ultimo_acerto.get(chave, 0) < 250:
        return
    ultimo_acerto[chave] = agora

    inimigo.hp -= DANO_JOGADOR.get(cliente["classe"], 20)

    if cliente["classe"] == 4:                    # teia do Pedro
        inimigo.lento_ate = agora + LENTO_TEIA_MS

    if inimigo.hp <= 0:
        inimigo.vivo = False
        inimigo.an = 0
        inimigo.acao_em = None
        print(f"[*] {cliente['nome']} derrotou {inimigo.st['nome']}")

        if cliente["classe"] == 0:                # Jaguatirica devora e se cura
            cliente["hp"] = min(VIDA_JOGADOR, cliente["hp"] + CURA_DEVORAR)


def aplicar_ferido(cid, cliente, msg):
    """O computador do jogador avisa que ele foi atingido. (chamar com a trava)
    Conferimos se o golpe existe e se estava perto dele (com folga para o atraso da internet)."""
    if cliente["hp"] <= 0:
        return

    agora = agora_ms()
    tipo = msg.get("k")
    ident = numero(msg.get("id"), -1)
    cx = cliente["x"] + JOGADOR_LARG / 2
    cy = cliente["y"] + JOGADOR_ALT / 2
    folga = esc(60)

    if tipo == "proj":
        for p in projeteis:
            if p["id"] == ident:
                vel = math.hypot(p["vx"], p["vy"])
                if math.hypot(p["x"] - cx, p["y"] - cy) <= p["r"] + folga + vel * TOLERANCIA_ATRASO_S:
                    dano_jogador(cliente, p["dano"], agora)
                projeteis.remove(p)           # o projétil some (acertou, ou era falso)
                return

    elif tipo == "onda":
        for o in ondas:
            if o["id"] == ident:
                if abs(o["x"] - cx) <= esc(150) + abs(o["vx"]) * TOLERANCIA_ATRASO_S:
                    dano_jogador(cliente, o["dano"], agora)
                return

    elif tipo == "zona":
        for z in zonas:
            if z["id"] == ident and cid not in z["feridos"]:
                z["feridos"].add(cid)
                tol = esc(150)
                if z["x"] - tol <= cx <= z["x"] + z["w"] + tol:
                    dano_jogador(cliente, z["dano"], agora)
                return

    elif tipo == "laser":
        if chefe and chefe.vivo and chefe.laser and chefe.laser["on"] == 1:
            dano_jogador(cliente, CHEFE["laser"]["dano"], agora)


def tratar(cid, cliente, msg):
    tipo = msg.get("t")

    if tipo == "entrar":
        nome = "".join(c for c in str(msg.get("nome", "Jogador"))
                       if c.isprintable()).strip()[:12] or "Jogador"
        classe = numero(msg.get("classe"), 0)
        if not 0 <= classe < TOTAL_CLASSES:
            classe = 0
        cliente.update(nome=nome, classe=classe, entrou=True,
                       hp=VIDA_JOGADOR, invul_ate=agora_ms() + 2000,
                       morto_ate=0)
        print(f"[+] {nome} entrou como classe {classe} "
              f"({len(clientes)} online)")

    elif tipo == "s" and cliente["entrou"]:
        cliente["x"] = numero(msg.get("x"))
        cliente["y"] = numero(msg.get("y"))
        cliente["d"] = -1 if numero(msg.get("d"), 1) < 0 else 1
        an = numero(msg.get("an"))
        cliente["an"] = an if 0 <= an <= 4 else 0
        cliente["tf"] = 1 if numero(msg.get("tf")) else 0

    elif tipo == "ev" and cliente["entrou"] and msg.get("k") == "proj":
        classe = numero(msg.get("c"), 0)
        if not 0 <= classe < TOTAL_CLASSES:
            return
        evento = {
            "t": "ev", "k": "proj", "id": cid, "c": classe,
            "x": numero(msg.get("x")), "y": numero(msg.get("y")),
            "d": -1 if numero(msg.get("d"), 1) < 0 else 1,
        }
        with trava:
            outros = [c for i, c in clientes.items() if i != cid]
        for outro in outros:
            enviar(outro, evento)

    elif tipo == "acerto" and cliente["entrou"]:
        with trava:
            aplicar_acerto(cid, cliente, msg)

    elif tipo == "ferido" and cliente["entrou"]:
        with trava:
            aplicar_ferido(cid, cliente, msg)

    elif tipo == "ping":                      # o jogo mede o atraso (ping) com isto
        enviar(cliente, {"t": "pong", "c": msg.get("c")})

    elif tipo == "nexus_iniciar" and cliente["entrou"]:
        with trava:
            iniciar_chefe(agora_ms())

    elif tipo == "renascer" and cliente["entrou"]:
        with trava:
            agora = agora_ms()
            batalha = chefe is not None and chefe.vivo     # na batalha ninguém renasce
            if cliente["hp"] <= 0 and agora >= cliente["morto_ate"] and not batalha:
                cliente["hp"] = VIDA_JOGADOR
                cliente["invul_ate"] = agora + 2000


# ---------------------------------------------------------
# CONEXÕES
# ---------------------------------------------------------
def remover(cid):
    with trava:
        cliente = clientes.pop(cid, None)
    if cliente is None:
        return
    try:
        cliente["conn"].close()
    except OSError:
        pass
    if cliente["entrou"]:
        print(f"[-] {cliente['nome']} saiu ({len(clientes)} online)")


def limitar_tempo_de_envio(sock, segundos=2.0):
    """Um jogador com internet ruim não pode travar o servidor inteiro."""
    try:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, int(segundos * 1000))
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO,
                            struct.pack("ll", int(segundos), int((segundos % 1) * 1e6)))
    except (OSError, AttributeError):
        pass


class ConexaoWS:
    """Faz um WebSocket se comportar como o socket TCP que o atender() usa."""

    def __init__(self, sock, inicial=b""):
        self.sock = sock
        self.leitor = ws.LeitorQuadros(sock.recv, inicial)
        self.trava_envio = threading.Lock()

    def setsockopt(self, *args):
        pass

    def sendall(self, dados):
        with self.trava_envio:
            self.sock.sendall(ws.construir_quadro(dados, ws.OP_TEXTO))

    def recv(self, n=0):
        """Texto da próxima mensagem; b"" quando a conexão fecha."""
        try:
            while True:
                op, dados = self.leitor.proximo()
                if op == ws.OP_FECHAR:
                    return b""
                if op == ws.OP_PING:
                    with self.trava_envio:
                        self.sock.sendall(ws.construir_quadro(dados, ws.OP_PONG))
                    continue
                if op == ws.OP_PONG or not dados:
                    continue
                if not dados.endswith(b"\n"):
                    dados += b"\n"
                return dados
        except (EOFError, ValueError, OSError):
            return b""

    def close(self):
        try:
            with self.trava_envio:
                self.sock.sendall(ws.construir_quadro(b"", ws.OP_FECHAR))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def ler_cabecalho_http(sock):
    """Lê o pedido HTTP. Devolve (primeira linha, cabeçalhos, bytes que sobraram)."""
    sock.settimeout(8)
    dados = b""
    while b"\r\n\r\n" not in dados:
        parte = sock.recv(4096)
        if not parte:
            raise OSError("conexão fechada")
        dados += parte
        if len(dados) > 16384:
            raise OSError("cabeçalho grande demais")

    cab, _, resto = dados.partition(b"\r\n\r\n")
    linhas = cab.decode("latin-1").split("\r\n")
    cabecalhos = {}
    for linha in linhas[1:]:
        if ":" in linha:
            k, _, v = linha.partition(":")
            cabecalhos[k.strip().lower()] = v.strip()
    return linhas[0], cabecalhos, resto


def responder_http(sock, status, tipo, corpo):
    corpo_b = corpo.encode()
    cab = (f"HTTP/1.1 {status}\r\nContent-Type: {tipo}; charset=utf-8\r\n"
           f"Content-Length: {len(corpo_b)}\r\nConnection: close\r\n"
           f"Access-Control-Allow-Origin: *\r\n\r\n").encode()
    sock.sendall(cab + corpo_b)


def status_json():
    with trava:
        em_jogo = sum(1 for c in clientes.values() if c["entrou"])
        conectados = len(clientes)
        mundo = FASES[fase_atual]["nome"]
    # tick_ms: tempo REAL entre atualizações (deveria ser ~1000/taxa). Se for muito
    # maior, o servidor está sem CPU (hospedagem grátis). trabalho_ms: custo de cada uma.
    return json.dumps({"jogo": "Tecnologia Fora de Controle", "jogadores": em_jogo,
                       "conectados": conectados, "max": MAX_JOGADORES, "mundo": mundo,
                       "taxa": TAXA, "tick_ms": round(media_tick_ms, 1),
                       "trabalho_ms": round(media_trabalho_ms, 2)})


def atender_ws(sock, endereco):
    """Porta WebSocket: o jogo (upgrade) ou um navegador/teste de saúde (HTTP)."""
    virou_ws = False
    try:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        primeira, cabecalhos, resto = ler_cabecalho_http(sock)
        partes = primeira.split(" ")
        caminho = partes[1] if len(partes) > 1 else "/"

        if (cabecalhos.get("upgrade", "").lower() == "websocket"
                and "sec-websocket-key" in cabecalhos):
            resposta = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {ws.chave_aceite(cabecalhos['sec-websocket-key'])}"
                        "\r\n\r\n")
            sock.sendall(resposta.encode())
            sock.settimeout(None)
            limitar_tempo_de_envio(sock)
            virou_ws = True
            atender(ConexaoWS(sock, resto), endereco)
        elif caminho.startswith("/status"):
            responder_http(sock, "200 OK", "application/json", status_json())
        else:
            responder_http(sock, "200 OK", "text/plain",
                           "Tecnologia Fora de Controle - servidor online.\n")
    except (OSError, ValueError, UnicodeError):
        pass
    finally:
        if not virou_ws:
            try:
                sock.close()
            except OSError:
                pass


def atender_tcp(conn, endereco):
    limitar_tempo_de_envio(conn)
    atender(conn, endereco)


def aceitar_loop(servidor, alvo):
    while True:
        try:
            conn, endereco = servidor.accept()
        except OSError:
            break
        threading.Thread(target=alvo, args=(conn, endereco), daemon=True).start()


def atender(conn, endereco):
    global proximo_id

    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    with trava:
        if len(clientes) >= MAX_JOGADORES:
            lotado = True
        else:
            lotado = False
            cid = proximo_id
            proximo_id += 1
            cliente = {"conn": conn, "nome": "?", "classe": 0,
                       "entrou": False, "x": 0, "y": 0, "d": 1,
                       "an": 0, "tf": 0, "hp": VIDA_JOGADOR,
                       "invul_ate": 0, "morto_ate": 0,
                       "envio": threading.Lock()}
            clientes[cid] = cliente

    if lotado:
        try:
            conn.sendall(codificar({"t": "erro", "msg": "Servidor cheio."}))
        except OSError:
            pass
        conn.close()
        return

    enviar(cliente, {"t": "bemvindo", "id": cid})
    buffer = b""

    try:
        while True:
            dados = conn.recv(4096)
            if not dados:
                break
            buffer += dados
            if len(buffer) > 65536:      # cliente mandando lixo
                break
            while b"\n" in buffer:
                linha, buffer = buffer.split(b"\n", 1)
                if not linha:
                    continue
                try:
                    msg = json.loads(linha)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    tratar(cid, cliente, msg)
    except OSError:
        pass
    finally:
        remover(cid)


def loop_do_mundo():
    """Simula os robôs e envia a todos o estado de tudo."""
    global media_tick_ms, media_trabalho_ms
    ultimo = time.monotonic()

    while True:
        time.sleep(1 / TAXA)
        agora_s = time.monotonic()
        periodo = agora_s - ultimo
        # Antes o passo era limitado a 0,1 s: se o servidor ficasse lento (hospedagem
        # grátis com pouca CPU), o JOGO inteiro andava em câmera lenta. Agora segue o
        # relógio real (limite 0,35 s só para não "pular" depois de uma pausa longa).
        dt = min(0.35, periodo)
        ultimo = agora_s
        media_tick_ms = 0.9 * media_tick_ms + 0.1 * periodo * 1000
        inicio_trabalho = time.monotonic()
        agora = int(agora_s * 1000)
        mortos = []

        with trava:
            if not clientes:
                continue

            vivos = [c for c in clientes.values()
                     if c["entrou"] and c["hp"] > 0]

            msg_fase = None
            if agora >= pausa_ate:               # fora da troca de mundo
                for inimigo in inimigos.values():
                    inimigo.atualizar(agora, dt, vivos)
                if chefe and chefe.vivo:
                    chefe.atualizar(agora, dt, vivos)
                atualizar_projeteis(agora, dt, vivos)
                atualizar_ondas(agora, dt, vivos)
                atualizar_zonas(agora)
                msg_fase = atualizar_portal(agora) or verificar_derrota_chefe(agora)

            if portal_aberto:
                dentro, total = contar_no_portal()
            else:
                dentro, total = 0, sum(1 for c in clientes.values() if c["entrou"])
            contagem = (max(0, int(contagem_ate - agora))
                        if contagem_ate is not None else -1)

            mundo = {
                str(i): {"x": c["x"], "y": c["y"], "d": c["d"],
                         "c": c["classe"], "n": c["nome"],
                         "an": c["an"], "tf": c["tf"], "hp": c["hp"]}
                for i, c in clientes.items() if c["entrou"]
            }
            lista_i = [[e.id, int(e.x), int(e.y), e.d, e.an, e.hp, e.idx]
                       for e in inimigos.values() if e.vivo]
            lista_p = [[p["id"], int(p["x"]), int(p["y"]),
                        int(p["vx"]), int(p["vy"]), p["tipo"]]
                       for p in projeteis]

            ativo = bool(chefe and chefe.vivo)
            if ativo:
                lista_i.append([BOSS_ID, int(chefe.x), int(chefe.y), chefe.d,
                                chefe.an, max(0, chefe.hp), TIPOS_BOSS_IDX])
            lista_o = [[o["id"], int(o["x"]), int(o["vx"])] for o in ondas]
            lista_z = [[z["id"], int(z["x"]), int(z["y"]), int(z["w"]), int(z["h"])]
                       for z in zonas if agora <= z["fim"]]
            info_chefe = ([int(ativo), max(0, chefe.hp), chefe.hp_max,
                           chefe.fase(), int(chefe_derrotado)]
                          if chefe else [0, 0, 0, 0, int(chefe_derrotado)])

            dados = codificar({
                "t": "mundo", "j": mundo, "i": lista_i, "p": lista_p,
                "f": [fase_atual, int(portal_aberto), dentro, total, contagem],
                "o": lista_o, "z": lista_z,
                "l": chefe.info_laser() if ativo else None,
                "bs": info_chefe,
            })
            if msg_fase:                         # avisa a troca de mundo antes
                dados = codificar(msg_fase) + dados
            if eventos:                          # ex.: o chefe morreu
                dados = b"".join(codificar(e) for e in eventos) + dados
                eventos.clear()

            for i, c in clientes.items():
                try:
                    with c["envio"]:
                        c["conn"].sendall(dados)
                except OSError:
                    mortos.append(i)

        for i in mortos:
            remover(i)

        media_trabalho_ms = 0.9 * media_trabalho_ms + 0.1 * (time.monotonic() - inicio_trabalho) * 1000


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))   # não envia nada, só descobre a rota
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def abrir_porta(porta, nome):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, porta))
        srv.listen()
        return srv
    except OSError as erro:
        print(f" AVISO: não consegui abrir a porta {porta} ({nome}): {erro}")
        srv.close()
        return None


def main():
    global fase_atual, PORTA_WS

    # python servidor.py --mundo 3   -> começa direto no mundo 3 (para testar)
    if "--mundo" in sys.argv:
        try:
            n = int(sys.argv[sys.argv.index("--mundo") + 1])
            fase_atual = max(0, min(len(FASES) - 1, n - 1))
        except (IndexError, ValueError):
            print("Use: python servidor.py --mundo 3")

    if "--ws" in sys.argv:
        try:
            PORTA_WS = int(sys.argv[sys.argv.index("--ws") + 1])
        except (IndexError, ValueError):
            print("Use: python servidor.py --ws 9000")

    criar_inimigos(fase_atual)

    srv_tcp = abrir_porta(PORTA, "rede local")
    srv_ws = abrir_porta(PORTA_WS, "WebSocket / internet")
    if srv_tcp is None and srv_ws is None:
        print(" Nenhuma porta abriu. Feche outro servidor aberto e tente de novo.")
        return

    print("=" * 56)
    print(" Servidor ligado!")
    print(f" {FASES[fase_atual]['nome']}: {len(inimigos)} robôs | máx. {MAX_JOGADORES} jogadores")
    if srv_tcp:
        print(f" Rede local, use:       {ip_local()}:{PORTA}")
        print(f" No seu PC, use:        127.0.0.1:{PORTA}")
    if srv_ws:
        print(f" WebSocket (internet):  porta {PORTA_WS}  (teste: ws://localhost:{PORTA_WS})")
        print(f" Teste no navegador:    http://localhost:{PORTA_WS}/status")
    print(" Ctrl+C para desligar")
    print("=" * 56)

    threading.Thread(target=loop_do_mundo, daemon=True).start()
    if srv_tcp:
        threading.Thread(target=aceitar_loop, args=(srv_tcp, atender_tcp), daemon=True).start()
    if srv_ws:
        threading.Thread(target=aceitar_loop, args=(srv_ws, atender_ws), daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServidor desligado.")
    finally:
        for srv in (srv_tcp, srv_ws):
            if srv:
                srv.close()


if __name__ == "__main__":
    main()