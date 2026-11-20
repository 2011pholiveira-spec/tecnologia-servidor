"""
MUNDO COMPARTILHADO - usado pelo jogo.py E pelo servidor.py.
Este arquivo precisa ser IGUAL nos dois lados (quem hospeda e quem joga).

Aqui ficam os números que o servidor e o jogo precisam concordar:
escala, chão, vida, dano e o comportamento de cada robô.
"""

# ---------------------------------------------------------
# ESCALA GLOBAL (mude aqui para deixar tudo maior ou menor)
# ---------------------------------------------------------
ESCALA = 1.5


def esc(valor):
    """Aplica a escala a um valor em pixels."""
    return int(round(valor * ESCALA))


CHAO_Y = 468
LARGURA_MUNDO = esc(4000)

# Hitbox do jogador
JOGADOR_LARG = esc(35)
JOGADOR_ALT = esc(50)

# ---------------------------------------------------------
# JOGADORES
# ---------------------------------------------------------
VIDA_JOGADOR = 100
INVUL_MS = 700                  # tempo sem levar dano depois de um golpe
TEMPO_RENASCER_MS = 3000

# Dano de cada personagem nos robôs (índice = id em CLASSES do jogo.py)
#            Jaguatirica, Sapé, Matheus, Mariana, Pedro
DANO_JOGADOR = {0: 60, 1: 45, 2: 25, 3: 30, 4: 18}
CURA_DEVORAR = 20               # a Jaguatirica recupera vida ao derrotar um robô
LENTO_TEIA_MS = 2500            # a teia do Pedro deixa o robô lento

# ---------------------------------------------------------
# ROBÔS
# Os nomes abaixo são os mesmos das pastas em img/
# ---------------------------------------------------------
TIPOS_INIMIGO = ["robosoldado", "roboatirador", "robocorpo", "robodrone",
                 "nexus"]          # o último é o chefe (mundo 3)

VISAO_Y = esc(260)              # diferença de altura máxima para um robô de chão te ver

# Velocidades em pixels POR SEGUNDO. Tempos em milissegundos.
#   hp / larg / alt  = vida e hitbox
#   ataque           = "tiro" ou "soco"
#   visao            = a que distância ele te enxerga
#   alcance          = distância para começar a atacar
#   intervalo        = tempo entre ataques | windup = preparo antes do golpe
#   mira             = True: o projétil vai na sua direção (drone)
STATS_INIMIGO = {
    "robosoldado": {
        "nome": "ROBÔ SOLDADO", "hp": 60, "larg": esc(40), "alt": esc(72),
        "voa": False, "ataque": "tiro",
        "vel": esc(60), "vel_persegue": esc(90),
        "visao": esc(450), "alcance": esc(380),
        "intervalo": 1700, "windup": 350, "recover": 250,
        "dano": 10, "proj_vel": esc(420), "proj_raio": esc(8),
        "proj_vida": 1400, "mira": False, "muzzle": 0.62,
    },
    "roboatirador": {
        "nome": "ROBÔ ATIRADOR", "hp": 80, "larg": esc(44), "alt": esc(78),
        "voa": False, "ataque": "tiro",
        "vel": esc(45), "vel_persegue": esc(70),
        "visao": esc(520), "alcance": esc(480),
        "intervalo": 2800, "windup": 600, "recover": 350,
        "dano": 22, "proj_vel": esc(260), "proj_raio": esc(18),
        "proj_vida": 2200, "mira": False, "muzzle": 0.6,
    },
    "robocorpo": {
        "nome": "ROBÔ SOCO", "hp": 130, "larg": esc(48), "alt": esc(86),
        "voa": False, "ataque": "soco",
        "vel": esc(60), "vel_persegue": esc(140),
        "visao": esc(380), "alcance": esc(40),       # distância até o alvo para socar
        "intervalo": 1300, "windup": 300, "recover": 350,
        "dano": 25, "golpe_larg": esc(80),
    },
    "robodrone": {
        "nome": "ROBÔ DRONE", "hp": 40, "larg": esc(46), "alt": esc(36),
        "voa": True, "y_voo": esc(140), "ataque": "tiro",
        "vel": esc(80), "vel_persegue": esc(110),
        "visao": esc(560), "alcance": esc(420),
        "intervalo": 1400, "windup": 250, "recover": 200,
        "dano": 8, "proj_vel": esc(500), "proj_raio": esc(7),
        "proj_vida": 1500, "mira": True, "muzzle": 0.5,
    },
}

# ---------------------------------------------------------
# CHEFE: NEXUS (mundo 3)
# Tempos em milissegundos, velocidades em pixels por segundo.
# ---------------------------------------------------------
BOSS_ID = 9000                  # id do chefe na lista de robôs
TEMPO_REINICIO_CHEFE_MS = 3000  # tela de "derrota" quando todos caem

STATS_INIMIGO["nexus"] = {
    "nome": "NEXUS", "hp": 2200, "larg": esc(90), "alt": esc(140),
    "voa": False, "proj_raio": esc(15),
}

CHEFE = {
    "hp": 2200,
    "hp_extra": 0.6,            # +60% de vida para cada jogador além do primeiro
    "nascer_ms": 3200,          # tempo saindo do chão (invulnerável)
    "vel": esc(85),             # velocidade andando
    "dist_ideal": esc(300),     # ele para de andar quando chega a essa distância
    "alcance_perto": esc(350),  # "perto": prefere pular em cima de você
    "fases": (0.66, 0.33),      # abaixo disso de vida ele fica mais rápido
    "pausa": (1500, 1150, 800), # tempo entre ataques em cada fase da batalha

    # 1) pula e cai no chão criando uma onda
    "salto": {"dano": 30, "dano_pisao": 35, "raio_pisao": esc(75),
              "alt_arco": esc(240), "dur": 1000, "alcance": esc(520),
              "pouso_ms": 650, "onda_vel": esc(430), "onda_larg": esc(46),
              "onda_alt": esc(36), "onda_vida": 1700},

    # 2) rajada de projéteis de plasma (3, 4 ou 5 conforme a fase)
    "disparo": {"dano": 18, "preparo": 450, "n": (3, 4, 5),
                "intervalo_tiro": 170, "vel": esc(400), "raio": esc(15),
                "vida": 2400, "espalha": 9, "recupera": 400},

    # 3) laser contínuo do peito, varrendo de cima para o chão
    "laser": {"dano": 14, "preparo": 900, "dur": 2500,
              "angulo_ini": 30, "angulo_fim": -22,
              "espessura": esc(32), "comprimento": esc(1200),
              "recupera": 600},
}


# ---------------------------------------------------------
# MUNDOS (FASES), OBJETOS, PLATAFORMAS E PORTAL
#
# Medidas em coordenadas ORIGINAIS (antes da escala).
#
#   objetos      = (tipo, x) peças sólidas no chão; x = lado esquerdo.
#                  Tipos: carro, escombros, muro (mundo 1)
#                         caixa, pilar, canteiro (mundo 2)
#   plataformas  = (x, altura) plataforma flutuante. altura = distância do
#                  chão até o TOPO dela. O pulo alcança uns 150 (≈232px);
#                  não passe de ~140 ou ela fica impossível de subir. Jogadores e robôs pisam em cima, e
#                  dá para atravessar por baixo (↓ ou S desce dela).
#   inimigos     = (tipo, x_min, x_max)            robô no chão, ou
#                  (tipo, x_min, x_max, altura)    robô em cima de plataforma.
#                  Cada robô patrulha só dentro da sua zona. Para ficar numa
#                  plataforma, a zona tem que caber dentro dela.
#   realce       = True: objetos mais claros + contorno + sombra (opcional)
#   y_voo        = altura dos drones neste mundo (opcional)
#   largura      = largura do mapa (opcional; padrão = LARGURA_MUNDO)
#   fundo_unico  = True: a imagem de fundo é o mapa INTEIRO (não repete)
#   chefe        = True: tem batalha contra o Nexus
#   dificuldade  = multiplicadores dos robôs deste mundo (1.0 = normal):
#                  hp, dano, vel (velocidade), reacao (menor = ataca mais
#                  rápido), visao (enxerga de mais longe), proj_vel
#                  (projétil mais rápido).
#
# Os robôs NÃO nascem de novo. Quando TODOS são derrotados, o portal abre
# em "portal_x". Quando TODOS os jogadores estiverem dentro dele ao mesmo
# tempo, todos vão para o próximo mundo. Depois do último mundo, volta ao 1.
# ---------------------------------------------------------
PORTAL_LARG = esc(80)            # largura da área do portal (quem estiver aqui conta)
PORTAL_ALT = esc(100)            # altura do portal na tela e da área
TEMPO_CONTAGEM_PORTAL_MS = 2000  # tempo com todos dentro antes de trocar de mundo
TEMPO_TRANSICAO_MS = 4000        # duração da tela de troca de mundo

PLATAFORMA_LARG = esc(180)       # largura da plataforma na tela
PLATAFORMA_ESPESSURA = esc(14)   # espessura da parte onde se pisa

# Altura dos objetos do mundo 2 (a largura segue a proporção da imagem).
# Vale para a parte VISÍVEL do desenho (as margens transparentes do PNG são
# cortadas). Se alguma imagem ficar grande/pequena demais, mude aqui.
ALTURA_OBJETOS = {"caixa": 70, "pilar": 120, "canteiro": 60}

FASES = [
    {   # ---------------- MUNDO 1: só Soldado e Drone (fácil) ----------------
        "nome": "MUNDO 1",
        "titulo": "CIDADE ABANDONADA - 2089",
        "fundo": "fundo_cidade",              # img/fundo_cidade.png
        "tela_entrada": None,                 # tela mostrada ao entrar neste mundo
        "elias": True,
        "portal_x": 3850,
        "dificuldade": {},
        "objetos": [
            ("carro",     560),
            ("escombros", 1000),
            ("muro",      1450),
            ("carro",     1950),
            ("escombros", 2160),
            ("muro",      2700),
            ("escombros", 3150),
            ("carro",     3380),
        ],
        "plataformas": [],
        "inimigos": [
            ("robosoldado",  770,  980),
            ("robodrone",   1100, 1700),
            ("robosoldado", 1730, 1930),
            ("robosoldado", 2370, 2680),
            ("robodrone",   2400, 3140),
            ("robosoldado", 2990, 3130),
            ("robosoldado", 3590, 3700),
        ],
    },
    {   # ------------- MUNDO 2: NEW METRUS (bem mais difícil) -------------
        "nome": "MUNDO 2",
        "titulo": "NEW METRUS - 2089",
        "fundo": "fundo_cidadetec",            # img/fundo_cidadetec.png
        "tela_entrada": "carregamentomundo2",  # img/carregamentomundo2.png
        "elias": False,
        "realce": True,        # objetos mais claros, com contorno e sombra (destaca do fundo)
        "y_voo": 215,          # altura em que os drones voam (acima das plataformas)
        "portal_x": 3850,
        "dificuldade": {"hp": 1.6, "dano": 1.4, "vel": 1.2,
                        "reacao": 0.75, "visao": 1.15, "proj_vel": 1.15},
        "objetos": [
            ("canteiro",  520),
            ("caixa",     900),
            ("pilar",    1300),
            ("canteiro", 2050),
            ("pilar",    2500),
            ("caixa",    2900),
            ("canteiro", 3250),
            ("pilar",    3500),
        ],
        "plataformas": [
            (700,  120),
            (1050, 135),
            (1450, 125),
            (1900, 135),     # só para pular (sem robô)
            (2250, 120),
            (2650, 140),
            (3050, 130),     # só para pular (sem robô)
            (3400, 135),
        ],
        "inimigos": [
            # no chão
            ("robosoldado",  680,  880),
            ("robocorpo",   1000, 1280),
            ("robocorpo",   1700, 2000),
            ("robosoldado", 2580, 2880),
            ("robocorpo",   3000, 3230),
            # em cima das plataformas
            ("robosoldado",  710,  870, 120),
            ("roboatirador", 1060, 1220, 135),
            ("robosoldado", 1460, 1620, 125),
            ("robosoldado", 2260, 2420, 120),
            ("roboatirador", 2660, 2820, 140),
            ("robocorpo",   3410, 3570, 135),
            # voando
            ("robodrone",   1000, 1800),
            ("robodrone",   2300, 3100),
        ],
    },
    {   # --------- MUNDO 3: COMPLEXO CENTRAL (só o chefe, sem robôs) ---------
        "nome": "MUNDO 3",
        "titulo": "COMPLEXO CENTRAL - 2089",
        "fundo": "fundo_complexo",             # img/fundo_complexo.png
        "fundo_unico": True,                   # UMA imagem = o mapa inteiro (sem repetir)
        "largura": 2700,                       # largura do mapa em pixels
        "piso_y": 620,                         # linha do chão DENTRO da imagem original
        "nexus_ancora_img": (1690, 400),       # ponto da imagem onde aponta o balão do Nexus
        "tela_entrada": "carregamentomundo3",  # img/carregamentomundo3.png
        "elias": False,
        "chefe": True,
        "nexus_x": 2134,                       # onde está a luz azul (o Nexus), em pixels
        "portal_x": None,                      # sem portal: o final são as 3 escolhas
        "dificuldade": {},
        "objetos": [],
        "plataformas": [],
        "inimigos": [],
    },
]


def tipos_usados():
    """Tipos de robô usados em algum mundo (o jogo só carrega esses sprites)."""
    usados = {item[0] for f in FASES for item in f["inimigos"]}
    if any(f.get("chefe") for f in FASES):
        usados.add("nexus")
    return [t for t in TIPOS_INIMIGO if t in usados]


def largura_do_mundo(fase=0):
    """Largura do mapa em pixels (cada mundo pode ter a sua)."""
    return FASES[fase].get("largura", LARGURA_MUNDO)


def stats_inimigo(tipo, fase=0):
    """Números do robô já com a dificuldade do mundo aplicada."""
    s = dict(STATS_INIMIGO[tipo])
    d = FASES[fase].get("dificuldade", {})

    s["hp"] = max(1, int(round(s["hp"] * d.get("hp", 1.0))))
    s["dano"] = max(1, int(round(s["dano"] * d.get("dano", 1.0))))
    s["vel"] = s["vel"] * d.get("vel", 1.0)
    s["vel_persegue"] = s["vel_persegue"] * d.get("vel", 1.0)
    s["visao"] = s["visao"] * d.get("visao", 1.0)
    s["intervalo"] = int(s["intervalo"] * d.get("reacao", 1.0))
    s["windup"] = int(s["windup"] * d.get("reacao", 1.0))
    if "proj_vel" in s:
        s["proj_vel"] = s["proj_vel"] * d.get("proj_vel", 1.0)
    if s.get("voa") and FASES[fase].get("y_voo"):
        s["y_voo"] = esc(FASES[fase]["y_voo"])
    return s


def hp_maximo(tipo, fase=0):
    return stats_inimigo(tipo, fase)["hp"]


def zonas_inimigos(fase=0):
    """Lista (tipo, x_min, x_max, altura_px) já com escala e com margem do
    tamanho do robô. altura_px = 0 no chão, ou a altura da plataforma."""
    zonas = []
    for item in FASES[fase]["inimigos"]:
        tipo, xmin, xmax = item[:3]
        altura = esc(item[3]) if len(item) > 3 else 0

        meia = STATS_INIMIGO[tipo]["larg"] // 2 + esc(10)
        zmin, zmax = esc(xmin) + meia, esc(xmax) - meia
        if zmax <= zmin:
            zmin = zmax = (esc(xmin) + esc(xmax)) // 2
        zonas.append((tipo, zmin, zmax, altura))
    return zonas