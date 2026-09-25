"""Autoclicker configuravel com tecla de atalho global e indicador visual."""

import ctypes
from ctypes import wintypes
import json
import math
import os
import random
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import winreg
from tkinter import ttk, messagebox, colorchooser

from pynput import keyboard, mouse
from PIL import Image, ImageDraw, ImageTk
import pystray

try:
    import winsound
except ImportError:
    winsound = None

APP_NAME = "ClickForge"
APP_VERSION = "1.0.0"
# owner/repo do GitHub usado pelo verificador de atualizações (releases).
UPDATE_REPO = "LuaMastery/ClickForge"

_SINGLE_INSTANCE_PORT = 47821

BUTTON_OPTIONS = ["Esquerdo", "Direito", "Meio", "Mouse 4 (Voltar)", "Mouse 5 (Avançar)"]
BUTTON_MAP = {
    "Esquerdo": mouse.Button.left,
    "Direito": mouse.Button.right,
    "Meio": mouse.Button.middle,
    "Mouse 4 (Voltar)": mouse.Button.x1,
    "Mouse 5 (Avançar)": mouse.Button.x2,
}

CLICK_TYPE_OPTIONS = ["Simples", "Duplo", "Triplo"]
CLICK_TYPE_COUNT = {"Simples": 1, "Duplo": 2, "Triplo": 3}

# Estilo de janela do Win32, usados para tornar o indicador visual
# "clicavel-atraves" (os cliques passam direto para o que está atrás dele).
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
LWA_COLORKEY = 0x00000001

MARKER_TRANSPARENT_COLOR = "magenta"
MARKER_COLORKEY = 0xFF00FF  # magenta em formato COLORREF (0x00BBGGRR)

# ---------------------------------------------------------------------------
# Hook global de mouse (WH_MOUSE_LL) usado para diferenciar, com certeza
# absoluta, um clique REAL do usuário de um clique SINTÉTICO gerado pelo
# próprio autoclique — mesmo quando os dois usam o mesmo botão (ex: segurar
# o botão esquerdo do mouse para ativar o autoclique NO botão esquerdo).
#
# Antes disso, a distinção era feita "contando" quantos eventos um clique
# sintético ia gerar e descontando esse número conforme os eventos chegavam
# no listener global (pynput). Isso é uma corrida: se o release REAL do
# usuário chegasse bem no instante em que ainda havia crédito pendente de um
# clique sintético, ele era descartado por engano como se fosse eco — e o
# autoclique nunca descobria que o botão tinha sido solto, ficando preso
# clicando para sempre (o bug crítico relatado).
#
# A primeira versão desse hook usava a flag LLMHF_INJECTED (que o Windows
# marca em todo evento gerado via SendInput) para reconhecer nossos próprios
# cliques. Isso tinha um problema sério: QUALQUER programa que injete
# entrada dessa forma — software de mouse/teclado de fabricante (Logitech,
# Razer, etc.), acesso remoto, máquinas virtuais, recursos de acessibilidade
# — também fica marcado como "injected", então o app acabava ignorando
# cliques/teclas reais do usuário sempre que algo assim estivesse ativo.
#
# Em vez disso, geramos nossos próprios cliques diretamente via SendInput
# (função _send_mouse_button) marcando um valor único em dwExtraInfo
# (AUTOCLICK_INPUT_TAG). O hook só ignora um evento se ELE MESMO tiver essa
# marca específica — qualquer outro evento, seja do hardware real ou
# injetado por outro programa, continua sendo tratado como entrada legítima
# do usuário.
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_QUIT = 0x0012
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

# Marca própria gravada em todo evento que NÓS geramos via SendInput (veja
# comentário acima). Um valor fixo e improvável de aparecer em entrada real.
AUTOCLICK_INPUT_TAG = 0xC0FFEE01

_MOUSE_HOOK_BUTTONS = {
    WM_LBUTTONDOWN: (mouse.Button.left, True),
    WM_LBUTTONUP: (mouse.Button.left, False),
    WM_RBUTTONDOWN: (mouse.Button.right, True),
    WM_RBUTTONUP: (mouse.Button.right, False),
    WM_MBUTTONDOWN: (mouse.Button.middle, True),
    WM_MBUTTONUP: (mouse.Button.middle, False),
}


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

# ---------------------------------------------------------------------------
# Hook global de teclado (WH_KEYBOARD_LL) — mesma ideia do hook de mouse
# acima, mas para teclas: necessário agora que uma ação de autoclique pode
# ser "pressionar uma tecla" em vez de "clicar o mouse". Sem isso, segurar
# uma tecla como gatilho para ficar pressionando ESSA MESMA tecla teria a
# mesma corrida crítica que foi corrigida para o mouse.
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

# Mapa reverso vk -> tecla especial do pynput (F1-F12, setas, Esc, etc.),
# construído a partir dos próprios valores que o pynput já usa no Windows —
# assim fica garantido que bate exatamente com o que o resto do app espera.
_VK_TO_SPECIAL_KEY = {}
for _k in keyboard.Key:
    _vk = getattr(getattr(_k, "value", None), "vk", None)
    if _vk is not None:
        _VK_TO_SPECIAL_KEY.setdefault(_vk, _k)


def _vk_event_to_key(vk, scan_code):
    """Traduz vkCode/scanCode do hook de teclado para uma tecla do pynput,
    respeitando Shift/CapsLock via ToUnicode (mesma técnica que o pynput usa
    internamente), para bater com o que o app já espera em outros lugares."""
    special = _VK_TO_SPECIAL_KEY.get(vk)
    if special is not None:
        return special
    try:
        state = (ctypes.c_byte * 256)()
        ctypes.windll.user32.GetKeyboardState(ctypes.byref(state))
        buf = ctypes.create_unicode_buffer(4)
        n = ctypes.windll.user32.ToUnicode(vk, scan_code, state, buf, 4, 0)
        if n > 0 and buf.value:
            return keyboard.KeyCode.from_char(buf.value[0])
    except Exception:
        pass
    return None


# Declara os tipos exatos dessas funções do Win32: sem isso, o ctypes assume
# retorno "int" de 32 bits por padrão, o que TRUNCA handles/ponteiros de 64
# bits (ex: o handle do hook) em Windows de 64 bits e corrompe o valor.
# O 2º parâmetro de SetWindowsHookExW fica como c_void_p (em vez do tipo
# exato do callback) porque ele é usado tanto para o hook de mouse quanto
# para o de teclado, que têm assinaturas de proc diferentes.
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_user32.SetWindowsHookExW.restype = wintypes.HANDLE
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HMODULE, wintypes.DWORD]
_user32.CallNextHookEx.restype = ctypes.c_ssize_t
_user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
_user32.GetMessageW.restype = ctypes.c_int
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


# ---------------------------------------------------------------------------
# Geração dos cliques/teclas sintéticos do próprio autoclique via SendInput
# direto (em vez do Controller do pynput), para poder marcar cada evento com
# AUTOCLICK_INPUT_TAG em dwExtraInfo — é assim que os hooks acima reconhecem
# com certeza "isso sou eu" sem depender da flag genérica "injected" do
# Windows (veja o comentário grande lá em cima).
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
KEYEVENTF_KEYUP = 0x0002


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32.SendInput.restype = wintypes.UINT
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]

_MOUSE_DOWN_FLAGS = {
    mouse.Button.left: MOUSEEVENTF_LEFTDOWN, mouse.Button.right: MOUSEEVENTF_RIGHTDOWN,
    mouse.Button.middle: MOUSEEVENTF_MIDDLEDOWN, mouse.Button.x1: MOUSEEVENTF_XDOWN,
    mouse.Button.x2: MOUSEEVENTF_XDOWN,
}
_MOUSE_UP_FLAGS = {
    mouse.Button.left: MOUSEEVENTF_LEFTUP, mouse.Button.right: MOUSEEVENTF_RIGHTUP,
    mouse.Button.middle: MOUSEEVENTF_MIDDLEUP, mouse.Button.x1: MOUSEEVENTF_XUP,
    mouse.Button.x2: MOUSEEVENTF_XUP,
}
_MOUSE_XDATA = {mouse.Button.x1: 1, mouse.Button.x2: 2}


def _send_mouse_button(button, down):
    inp = _INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.mouseData = _MOUSE_XDATA.get(button, 0)
    inp.mi.dwFlags = (_MOUSE_DOWN_FLAGS if down else _MOUSE_UP_FLAGS).get(button, 0)
    inp.mi.dwExtraInfo = AUTOCLICK_INPUT_TAG
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _synthetic_click(button, count=1):
    for _ in range(max(1, count)):
        _send_mouse_button(button, True)
        _send_mouse_button(button, False)


def _key_to_vk_scan(key):
    """Resolve uma tecla do pynput (especial ou de caractere) para o par
    (vk, scancode) que o SendInput precisa."""
    if key is None:
        return None, None
    vk = getattr(key, "vk", None)
    if vk is None and isinstance(key, keyboard.KeyCode) and key.char:
        res = ctypes.windll.user32.VkKeyScanW(key.char)
        if res != -1:
            vk = res & 0xFF
    if vk is None:
        return None, None
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    return vk, scan


def _send_key(vk, scan, down):
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = 0 if down else KEYEVENTF_KEYUP
    inp.ki.dwExtraInfo = AUTOCLICK_INPUT_TAG
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _build_tray_image():
    """Gera o ícone da bandeja na hora (cursor com anéis de clique), sem
    depender de arquivo externo — assim funciona igual dentro do .exe."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=14, fill=(37, 99, 235, 255))
    cursor = [
        (18, 14), (18, 47), (26, 40), (32, 51),
        (37, 48), (31, 38), (43, 38),
    ]
    draw.polygon(cursor, fill=(255, 255, 255, 255))
    draw.ellipse([38, 20, 46, 28], fill=(250, 204, 21, 255))
    return img


def _migrate_old_appdata_dir(dir_path):
    """O app se chamava "AutoClicker" antes de virar ClickForge — na primeira
    vez que roda com o nome novo, copia a pasta de dados antiga (config e
    perfis) para não perder o que o usuário já tinha configurado."""
    base = os.path.dirname(dir_path)
    old_dir = os.path.join(base, "AutoClicker")
    if os.path.isdir(old_dir) and not os.path.isdir(dir_path):
        try:
            import shutil
            shutil.copytree(old_dir, dir_path)
        except OSError:
            pass


def _appdata_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    dir_path = os.path.join(base, APP_NAME)
    if not os.path.isdir(dir_path):
        _migrate_old_appdata_dir(dir_path)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def _config_path():
    return os.path.join(_appdata_dir(), "config.json")


def _profiles_path():
    return os.path.join(_appdata_dir(), "profiles.json")


# ---------------------------------------------------------------------------
# "Iniciar com o Windows": grava/remove uma entrada em
# HKCU\...\CurrentVersion\Run, que é o mesmo mecanismo (sem precisar de
# administrador) que apps como Discord ou Spotify usam para isso. Só é
# alterado quando o usuário marca/desmarca a caixa na aba Interface — nada é
# escrito no registro automaticamente sem essa ação explícita dele.
_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = APP_NAME
_OLD_RUN_VALUE_NAME = "AutoClicker"


def _startup_command():
    # A flag "--startup" permite ao app, ao ser aberto, saber que a origem
    # foi essa entrada de inicialização (e não um clique manual no atalho) —
    # é o que possibilita a opção "iniciar oculto" só se aplicar aqui.
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}" --startup'


def _cleanup_old_run_value():
    """Remove a entrada de inicialização com o nome antigo "AutoClicker",
    deixada por versões anteriores do app antes de virar ClickForge."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, _OLD_RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    except OSError:
        pass


def _is_run_on_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
            return value == _startup_command()
    except OSError:
        return False


def _set_run_on_startup(enabled):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Verificação de atualizações: consulta a última release publicada no GitHub
# (UPDATE_REPO) e, se for mais nova que APP_VERSION, baixa o .exe anexado a
# ela. A troca do arquivo só é feita depois que o app fechar de verdade (veja
# _quit_app), usando um script auxiliar que espera o processo atual encerrar,
# substitui o .exe e abre a versão nova — assim nunca mexe num arquivo que
# ainda está em uso.
def _parse_version(text):
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _fetch_latest_release():
    url = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-updater"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _serialize_key(key):
    if isinstance(key, keyboard.Key):
        return {"type": "special", "name": key.name}
    if isinstance(key, keyboard.KeyCode) and key.char:
        return {"type": "char", "char": key.char}
    return None


def _deserialize_key(data):
    if not data:
        return None
    if data.get("type") == "special":
        try:
            return keyboard.Key[data["name"]]
        except KeyError:
            return None
    if data.get("type") == "char" and data.get("char"):
        return keyboard.KeyCode.from_char(data["char"])
    return None


SPECIAL_KEY_NAMES = {
    keyboard.Key.f1: "F1", keyboard.Key.f2: "F2", keyboard.Key.f3: "F3",
    keyboard.Key.f4: "F4", keyboard.Key.f5: "F5", keyboard.Key.f6: "F6",
    keyboard.Key.f7: "F7", keyboard.Key.f8: "F8", keyboard.Key.f9: "F9",
    keyboard.Key.f10: "F10", keyboard.Key.f11: "F11", keyboard.Key.f12: "F12",
    keyboard.Key.esc: "Esc", keyboard.Key.space: "Espaço",
    keyboard.Key.tab: "Tab", keyboard.Key.caps_lock: "Caps Lock",
    keyboard.Key.page_up: "Page Up", keyboard.Key.page_down: "Page Down",
    keyboard.Key.home: "Home", keyboard.Key.end: "End",
    keyboard.Key.insert: "Insert", keyboard.Key.delete: "Delete",
}


def key_to_label(key):
    """Converte um objeto de tecla do pynput em um texto legivel."""
    if key is None:
        return "nenhuma"
    if key in SPECIAL_KEY_NAMES:
        return SPECIAL_KEY_NAMES[key]
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char.upper()
    return str(key).replace("Key.", "").upper()


MOUSE_TRIGGER_LABELS = {
    mouse.Button.left: "Mouse Esquerdo",
    mouse.Button.right: "Mouse Direito",
    mouse.Button.middle: "Mouse Meio",
    mouse.Button.x1: "Mouse 4 (Voltar)",
    mouse.Button.x2: "Mouse 5 (Avançar)",
}


def trigger_to_label(trigger):
    """Converte um gatilho (tecla ou botão do mouse) em texto legivel.

    Um gatilho e uma tupla ("keyboard", tecla) ou ("mouse", botao), ou None.
    """
    if trigger is None:
        return "nenhuma"
    kind, value = trigger
    if kind == "mouse":
        return MOUSE_TRIGGER_LABELS.get(value, str(value))
    return key_to_label(value)


def _serialize_trigger(trigger):
    if trigger is None:
        return None
    kind, value = trigger
    if kind == "keyboard":
        data = _serialize_key(value)
        if data is None:
            return None
        data["kind"] = "keyboard"
        return data
    if kind == "mouse":
        return {"kind": "mouse", "name": value.name}
    return None


def _deserialize_trigger(data):
    if not data:
        return None
    # Configs antigos guardavam a tecla sem o campo "kind" (era sempre teclado).
    kind = data.get("kind", "keyboard")
    if kind == "mouse":
        try:
            return ("mouse", mouse.Button[data["name"]])
        except KeyError:
            return None
    key = _deserialize_key(data)
    return ("keyboard", key) if key is not None else None


def triggers_equal(a, b):
    return a is not None and b is not None and a[0] == b[0] and a[1] == b[1]


class AutoClickerApp:
    def __init__(self, root, launched_via_startup=False):
        self.root = root
        self.launched_via_startup = launched_via_startup
        self.root.title(APP_NAME)
        self.root.resizable(False, False)

        self.running = False
        self.click_count = 0
        # Uma única thread de trabalho vive por toda a sessão do app, em vez
        # de criar/destruir uma thread a cada início/parada — isso evitava
        # engasgos perceptíveis quando o usuário liga/desliga o autoclique
        # com frequência (ex: segurando e soltando o gatilho repetidas
        # vezes), já que criar uma thread do sistema operacional não é uma
        # operação instantânea. "run_event" acorda a thread para começar um
        # ciclo; "stop_now_event" interrompe o ciclo atual na hora.
        self.run_event = threading.Event()
        self.stop_now_event = threading.Event()
        self.shutting_down = False
        self.run_params = None
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.lock_socket = None

        # Usado só para ler/mover a posição do cursor (clique com posição
        # fixa) — os cliques em si são gerados via SendInput direto (veja
        # _send_mouse_button), não por este Controller.
        self.mouse_ctrl = mouse.Controller()

        # Gatilhos: tupla ("keyboard", tecla) ou ("mouse", botao).
        self.hotkey = ("keyboard", keyboard.Key.f6)
        self.stop_key = None
        self.listening_for_hotkey = False
        self.listening_for_stopkey = False
        # Tecla usada como AÇÃO (quando o clicker principal está no modo
        # "pressionar tecla" em vez de "clicar mouse").
        self.action_key = None
        self.listening_for_action_key = False
        # Callback genérico usado pelos diálogos de edição dos clickers
        # extras (aba "Múltiplos") para capturar um gatilho ou uma tecla de
        # ação sem precisar de um flag booleano dedicado para cada um.
        self._capture_callback = None

        # Sistema antigo de eco por contagem — mantido apenas como
        # salva-vidas para o raro caso em que o hook de baixo nível (abaixo)
        # não consiga ser instalado neste Windows. Enquanto o hook estiver
        # ativo, nada disto é usado.
        self.echo_lock = threading.Lock()
        self.echo_button = None
        self.pending_echo_count = 0

        self._using_raw_mouse_hook = False
        self._using_raw_kb_hook = False
        self._hook_mouse_id = None
        self._hook_kb_id = None
        self._hook_thread_id = None
        self._mouse_hook_proc_ref = None
        self._kb_hook_proc_ref = None
        self.mouse_listener = None
        self.kb_listener = None

        self.fixed_pos = None
        self.capturing_pos = False

        self.marker_window = None
        self.marker_canvas = None

        # Autocliques extras, gerenciados pela aba "Múltiplos" — cada um roda
        # de forma totalmente independente do clicker principal acima.
        self.clickers = []

        self._build_ui()
        self._load_config()
        self._refresh_profile_list()
        self._refresh_marker()

        try:
            self._app_icon_image = ImageTk.PhotoImage(_build_tray_image())
            self.root.iconphoto(True, self._app_icon_image)
        except Exception:
            pass

        self._using_raw_mouse_hook, self._using_raw_kb_hook = self._install_input_hooks()

        if not self._using_raw_kb_hook:
            # Fallback raríssimo: hook de baixo nível não pôde ser instalado.
            self.kb_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
            self.kb_listener.daemon = True
            self.kb_listener.start()

        if not self._using_raw_mouse_hook:
            self.mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()

        self.worker_thread.start()

        self._notified_background = False
        self.tray_icon = pystray.Icon(
            APP_NAME,
            _build_tray_image(),
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Mostrar janela", self._tray_show, default=True),
                pystray.MenuItem("Iniciar/Parar autoclique", self._tray_toggle),
                pystray.MenuItem("Verificar atualizações", self._tray_check_updates),
                pystray.MenuItem("Sair", self._tray_quit),
            ),
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

        if self.launched_via_startup and self.var_start_hidden.get():
            # A janela já começou escondida (main() chamou withdraw() antes
            # de criar o app) — só avisa pela bandeja que está rodando.
            self._notified_background = True
            try:
                self.tray_icon.notify(
                    f"O {APP_NAME} iniciou em segundo plano. Clique no ícone da bandeja para abrir.",
                    APP_NAME,
                )
            except Exception:
                pass
        elif self.launched_via_startup:
            self.root.deiconify()

        self._pending_update_path = None
        threading.Thread(target=self._check_for_update, args=(False,), daemon=True).start()

    # ---------- UI ----------

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")

        notebook = ttk.Notebook(main)
        notebook.grid(row=0, column=0, sticky="nsew")

        tab_clique = ttk.Frame(notebook, padding=8)
        tab_intervalo = ttk.Frame(notebook, padding=8)
        tab_posicao = ttk.Frame(notebook, padding=8)
        tab_repeticao = ttk.Frame(notebook, padding=8)
        tab_atalhos = ttk.Frame(notebook, padding=8)
        tab_multi = ttk.Frame(notebook, padding=8)
        tab_interface = ttk.Frame(notebook, padding=8)
        tab_perfis = ttk.Frame(notebook, padding=8)

        notebook.add(tab_clique, text="Clique")
        notebook.add(tab_intervalo, text="Intervalo")
        notebook.add(tab_posicao, text="Posição")
        notebook.add(tab_repeticao, text="Repetição")
        notebook.add(tab_atalhos, text="Atalhos")
        notebook.add(tab_multi, text="Múltiplos")
        notebook.add(tab_interface, text="Interface")
        notebook.add(tab_perfis, text="Perfis")

        self._build_tab_clique(tab_clique)
        self._build_tab_intervalo(tab_intervalo)
        self._build_tab_posicao(tab_posicao)
        self._build_tab_repeticao(tab_repeticao)
        self._build_tab_atalhos(tab_atalhos)
        self._build_tab_multi(tab_multi)
        self._build_tab_interface(tab_interface)
        self._build_tab_perfis(tab_perfis)

        # Status e controle (sempre visível, fora das abas)
        ctrl_frame = ttk.Frame(main)
        ctrl_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.lbl_status = ttk.Label(ctrl_frame, text="Parado", foreground="red", font=("Segoe UI", 11, "bold"))
        self.lbl_status.grid(row=0, column=0, sticky="w", padx=6)

        self.lbl_count = ttk.Label(ctrl_frame, text="Cliques: 0")
        self.lbl_count.grid(row=0, column=1, sticky="w", padx=6)

        self.btn_toggle = ttk.Button(ctrl_frame, text="Iniciar (ou pressione a tecla)", command=self.toggle)
        self.btn_toggle.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        ctrl_frame.columnconfigure(0, weight=1)
        ctrl_frame.columnconfigure(1, weight=1)

    def _build_tab_clique(self, tab):
        action_frame = ttk.LabelFrame(tab, text="Tipo de ação")
        action_frame.grid(row=0, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 8))

        self.var_action_kind = tk.StringVar(value="mouse")
        ttk.Radiobutton(
            action_frame, text="Clicar com o mouse", value="mouse", variable=self.var_action_kind,
            command=self._refresh_action_kind_state,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            action_frame, text="Pressionar uma tecla do teclado", value="keyboard", variable=self.var_action_kind,
            command=self._refresh_action_kind_state,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.lbl_action_key = ttk.Label(action_frame, text=f"Tecla: {key_to_label(self.action_key)}")
        self.lbl_action_key.grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.btn_action_key = ttk.Button(
            action_frame, text="Definir tecla...", command=self._start_action_key_capture,
        )
        self.btn_action_key.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(tab, text="Botão:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.var_button = tk.StringVar(value="Esquerdo")
        self.combo_button = ttk.Combobox(
            tab, textvariable=self.var_button, width=18, state="readonly", values=BUTTON_OPTIONS,
        )
        self.combo_button.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(tab, text="Tipo:").grid(row=1, column=2, padx=6, pady=6, sticky="w")
        self.var_click_type = tk.StringVar(value="Simples")
        self.combo_click_type = ttk.Combobox(
            tab, textvariable=self.var_click_type, width=10, state="readonly", values=CLICK_TYPE_OPTIONS,
        )
        self.combo_click_type.grid(row=1, column=3, padx=6, pady=6, sticky="w")

        press_frame = ttk.LabelFrame(tab, text="Modo de pressão")
        press_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=6, pady=(10, 6))

        self.var_press_mode = tk.StringVar(value="Clique único")
        ttk.Radiobutton(
            press_frame, text="Clique único", value="Clique único", variable=self.var_press_mode,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            press_frame, text="Segurar pressionado por:", value="Segurar pressionado", variable=self.var_press_mode,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.var_hold_ms = tk.StringVar(value="50")
        ttk.Entry(press_frame, textvariable=self.var_hold_ms, width=8).grid(row=1, column=1, padx=4, pady=4)
        ttk.Label(press_frame, text="ms").grid(row=1, column=2, sticky="w")

        self._refresh_action_kind_state()

    def _refresh_action_kind_state(self):
        is_mouse = self.var_action_kind.get() == "mouse"
        self.combo_button.config(state="readonly" if is_mouse else "disabled")
        self.combo_click_type.config(state="readonly" if is_mouse else "disabled")
        self.btn_action_key.config(state="disabled" if is_mouse else "normal")

    def _start_action_key_capture(self):
        self.listening_for_action_key = True
        self.lbl_action_key.config(text="Pressione uma tecla...")

    def _build_tab_intervalo(self, tab):
        base_frame = ttk.LabelFrame(tab, text="Intervalo base entre cliques")
        base_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        self.var_h = tk.StringVar(value="0")
        self.var_m = tk.StringVar(value="0")
        self.var_s = tk.StringVar(value="0")
        self.var_ms = tk.StringVar(value="100")

        for i, (label, var) in enumerate([
            ("Horas", self.var_h), ("Min", self.var_m),
            ("Seg", self.var_s), ("Ms", self.var_ms),
        ]):
            ttk.Label(base_frame, text=label).grid(row=0, column=i * 2, padx=(6, 2), pady=6)
            ttk.Entry(base_frame, textvariable=var, width=6).grid(row=0, column=i * 2 + 1, padx=(0, 6), pady=6)

        jitter_frame = ttk.LabelFrame(tab, text="Variação aleatória de intervalo")
        jitter_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

        self.var_random_interval = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            jitter_frame, text="Somar um atraso extra aleatório a cada clique", variable=self.var_random_interval,
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=4)

        ttk.Label(jitter_frame, text="Mínimo (ms):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.var_jitter_min = tk.StringVar(value="0")
        ttk.Entry(jitter_frame, textvariable=self.var_jitter_min, width=8).grid(row=1, column=1, padx=4, pady=4)

        ttk.Label(jitter_frame, text="Máximo (ms):").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        self.var_jitter_max = tk.StringVar(value="50")
        ttk.Entry(jitter_frame, textvariable=self.var_jitter_max, width=8).grid(row=1, column=3, padx=4, pady=4)

    def _build_tab_posicao(self, tab):
        pos_frame = ttk.LabelFrame(tab, text="Posição do clique")
        pos_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        self.var_position_mode = tk.StringVar(value="Posição atual do mouse")
        ttk.Radiobutton(
            pos_frame, text="Posição atual do mouse", value="Posição atual do mouse",
            variable=self.var_position_mode, command=self._refresh_marker,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Radiobutton(
            pos_frame, text="Posição fixa:", value="Posição fixa",
            variable=self.var_position_mode, command=self._refresh_marker,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.lbl_fixed_pos = ttk.Label(pos_frame, text="não definida")
        self.lbl_fixed_pos.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Button(pos_frame, text="Capturar posição (3s)", command=self._start_capture_position).grid(
            row=1, column=2, padx=6, pady=4
        )

        random_frame = ttk.LabelFrame(tab, text="Variação aleatória de posição")
        random_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

        self.var_random_pos = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            random_frame, text="Espalhar o clique em volta da posição fixa", variable=self.var_random_pos,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(random_frame, text="Raio (px):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.var_pos_radius = tk.StringVar(value="5")
        ttk.Entry(random_frame, textvariable=self.var_pos_radius, width=8).grid(row=1, column=1, padx=4, pady=4, sticky="w")

        marker_frame = ttk.LabelFrame(tab, text="Indicador visual")
        marker_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=6)

        self.var_show_marker = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            marker_frame, text="Mostrar um marcador na tela sobre a posição fixa",
            variable=self.var_show_marker, command=self._refresh_marker,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        self.var_marker_color = tk.StringVar(value="#facc15")
        ttk.Button(marker_frame, text="Cor do indicador...", command=self._pick_marker_color).grid(
            row=1, column=0, padx=6, pady=4, sticky="w"
        )

        misc_frame = ttk.LabelFrame(tab, text="Outros")
        misc_frame.grid(row=3, column=0, sticky="ew", padx=6, pady=6)

        self.var_return_pos = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            misc_frame, text="Voltar o mouse à posição original depois de cada clique",
            variable=self.var_return_pos,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)

    def _build_tab_repeticao(self, tab):
        rep_frame = ttk.LabelFrame(tab, text="Quando parar")
        rep_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        self.var_repeat_mode = tk.StringVar(value="Até parar manualmente")
        ttk.Radiobutton(
            rep_frame, text="Até parar manualmente", value="Até parar manualmente",
            variable=self.var_repeat_mode,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Radiobutton(
            rep_frame, text="Número fixo de cliques:", value="Número fixo",
            variable=self.var_repeat_mode,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.var_repeat_count = tk.StringVar(value="10")
        ttk.Entry(rep_frame, textvariable=self.var_repeat_count, width=8).grid(row=1, column=1, padx=4, pady=4)

        ttk.Radiobutton(
            rep_frame, text="Por duração:", value="Por duração",
            variable=self.var_repeat_mode,
        ).grid(row=2, column=0, sticky="w", padx=6, pady=4)

        self.var_dur_h = tk.StringVar(value="0")
        self.var_dur_m = tk.StringVar(value="0")
        self.var_dur_s = tk.StringVar(value="10")
        for i, (label, var) in enumerate([
            ("h", self.var_dur_h), ("min", self.var_dur_m), ("seg", self.var_dur_s),
        ]):
            ttk.Entry(rep_frame, textvariable=var, width=5).grid(row=2, column=1 + i * 2, padx=(4, 2), pady=4)
            ttk.Label(rep_frame, text=label).grid(row=2, column=2 + i * 2, sticky="w")

        delay_frame = ttk.LabelFrame(tab, text="Atraso inicial")
        delay_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

        ttk.Label(delay_frame, text="Esperar antes do primeiro clique (segundos):").grid(
            row=0, column=0, sticky="w", padx=6, pady=4
        )
        self.var_start_delay = tk.StringVar(value="0")
        ttk.Entry(delay_frame, textvariable=self.var_start_delay, width=8).grid(row=0, column=1, padx=4, pady=4)

    def _build_tab_atalhos(self, tab):
        toggle_frame = ttk.LabelFrame(tab, text="Tecla ou botão do mouse (liga/desliga)")
        toggle_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        ttk.Label(
            toggle_frame, text="Pode ser uma tecla do teclado ou um botão do mouse (inclusive Mouse 4/5).",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0))

        self.lbl_hotkey = ttk.Label(
            toggle_frame, text=f"Tecla atual: {trigger_to_label(self.hotkey)}", font=("Segoe UI", 10, "bold")
        )
        self.lbl_hotkey.grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(toggle_frame, text="Definir novo atalho", command=self._start_hotkey_capture).grid(
            row=1, column=1, padx=6, pady=6
        )

        self.var_hotkey_mode = tk.StringVar(value="Alternar")
        ttk.Radiobutton(
            toggle_frame, text="Alternar (aperte para ligar, aperte de novo para desligar)",
            value="Alternar", variable=self.var_hotkey_mode,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 2))
        ttk.Radiobutton(
            toggle_frame, text="Segurar para ativar (mantenha pressionado; solte para parar)",
            value="Segurar", variable=self.var_hotkey_mode,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        stop_frame = ttk.LabelFrame(tab, text="Tecla de parada de emergência")
        stop_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

        ttk.Label(stop_frame, text="Sempre para o autoclique, mesmo com os atalhos desativados abaixo.").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0)
        )
        self.lbl_stop_key = ttk.Label(
            stop_frame, text=f"Tecla atual: {trigger_to_label(self.stop_key)}", font=("Segoe UI", 10, "bold")
        )
        self.lbl_stop_key.grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(stop_frame, text="Definir tecla de parada", command=self._start_stopkey_capture).grid(
            row=1, column=1, padx=6, pady=6
        )

        master_frame = ttk.LabelFrame(tab, text="Geral")
        master_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=6)

        self.var_hotkeys_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            master_frame, text="Ativar atalhos globais (tecla/botão de liga/desliga)",
            variable=self.var_hotkeys_enabled,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)

    def _build_tab_multi(self, tab):
        info = ttk.Label(
            tab,
            text=(
                "Crie e gerencie vários autocliques independentes, cada um\n"
                "com seu próprio gatilho, intervalo e ação (mouse ou teclado)."
            ),
            justify="left",
        )
        info.grid(row=0, column=0, sticky="w", padx=6, pady=(0, 10))

        columns = ("nome", "acao", "gatilho", "status")
        self.tree_clickers = ttk.Treeview(tab, columns=columns, show="headings", height=8)
        for col, label, width in [
            ("nome", "Nome", 100), ("acao", "Ação", 170),
            ("gatilho", "Gatilho", 130), ("status", "Status", 80),
        ]:
            self.tree_clickers.heading(col, text=label)
            self.tree_clickers.column(col, width=width, anchor="w")
        self.tree_clickers.grid(row=1, column=0, sticky="ew", padx=6, pady=4)

        btns = ttk.Frame(tab)
        btns.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(btns, text="Novo clicker...", command=self._new_clicker).grid(row=0, column=0, padx=3)
        ttk.Button(btns, text="Editar...", command=self._edit_selected_clicker).grid(row=0, column=1, padx=3)
        ttk.Button(btns, text="Iniciar/Parar", command=self._toggle_selected_clicker).grid(row=0, column=2, padx=3)
        ttk.Button(btns, text="Remover", command=self._remove_selected_clicker).grid(row=0, column=3, padx=3)

        self._refresh_clicker_list()

    def _refresh_clicker_list(self):
        tree = self.tree_clickers
        selected = self._selected_clicker_index()
        tree.delete(*tree.get_children())
        for i, c in enumerate(self.clickers):
            status = "Rodando" if c.running else "Parado"
            tree.insert("", "end", iid=str(i), values=(c.name, c.action_label(), trigger_to_label(c.trigger), status))
        if selected is not None and str(selected) in tree.get_children():
            tree.selection_set(str(selected))

    def _selected_clicker_index(self):
        sel = self.tree_clickers.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _new_clicker(self):
        c = ClickerInstance(self)
        self.clickers.append(c)
        self._refresh_clicker_list()
        self._open_clicker_editor(c)

    def _edit_selected_clicker(self):
        idx = self._selected_clicker_index()
        if idx is None:
            messagebox.showerror("Erro", "Selecione um clicker na lista.")
            return
        self._open_clicker_editor(self.clickers[idx])

    def _toggle_selected_clicker(self):
        idx = self._selected_clicker_index()
        if idx is None:
            messagebox.showerror("Erro", "Selecione um clicker na lista.")
            return
        self.clickers[idx].toggle()

    def _remove_selected_clicker(self):
        idx = self._selected_clicker_index()
        if idx is None:
            messagebox.showerror("Erro", "Selecione um clicker na lista.")
            return
        c = self.clickers.pop(idx)
        c.shutting_down = True
        c.stop_now_event.set()
        c.run_event.set()
        self._refresh_clicker_list()

    def _open_clicker_editor(self, clicker):
        win = tk.Toplevel(self.root)
        win.title(f"Editar {clicker.name}")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        pad = dict(padx=6, pady=4)
        frm = ttk.Frame(win, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        row = 0

        ttk.Label(frm, text="Nome:").grid(row=row, column=0, sticky="w", **pad)
        var_name = tk.StringVar(value=clicker.name)
        ttk.Entry(frm, textvariable=var_name, width=26).grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1

        action_frame = ttk.LabelFrame(frm, text="Ação")
        action_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        row += 1

        var_action_kind = tk.StringVar(value=clicker.action_kind)
        ttk.Radiobutton(
            action_frame, text="Botão do mouse", value="mouse", variable=var_action_kind,
            command=lambda: _refresh_action_state(),
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            action_frame, text="Tecla do teclado", value="keyboard", variable=var_action_kind,
            command=lambda: _refresh_action_state(),
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        button_label = next((k for k, v in BUTTON_MAP.items() if v == clicker.button), "Esquerdo")
        var_button = tk.StringVar(value=button_label)
        combo_button = ttk.Combobox(
            action_frame, textvariable=var_button, width=16, state="readonly", values=BUTTON_OPTIONS,
        )
        combo_button.grid(row=1, column=0, sticky="w", padx=6, pady=4)

        var_click_type = tk.StringVar(value=clicker.click_type)
        combo_click_type = ttk.Combobox(
            action_frame, textvariable=var_click_type, width=10, state="readonly", values=CLICK_TYPE_OPTIONS,
        )
        combo_click_type.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        var_action_key_label = tk.StringVar(value=f"Tecla: {key_to_label(clicker.action_key)}")
        ttk.Label(action_frame, textvariable=var_action_key_label).grid(row=2, column=0, sticky="w", padx=6, pady=4)

        captured_action_key = {"value": clicker.action_key}

        def _on_action_key_captured(trigger):
            if trigger[0] != "keyboard":
                return
            captured_action_key["value"] = trigger[1]
            var_action_key_label.set(f"Tecla: {key_to_label(trigger[1])}")

        def _capture_action_key():
            var_action_key_label.set("Pressione uma tecla...")
            self._capture_callback = _on_action_key_captured

        btn_action_key = ttk.Button(action_frame, text="Definir tecla...", command=_capture_action_key)
        btn_action_key.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        def _refresh_action_state():
            is_mouse = var_action_kind.get() == "mouse"
            combo_button.config(state="readonly" if is_mouse else "disabled")
            combo_click_type.config(state="readonly" if is_mouse else "disabled")
            btn_action_key.config(state="disabled" if is_mouse else "normal")

        _refresh_action_state()

        press_frame = ttk.LabelFrame(frm, text="Modo de pressão")
        press_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        row += 1
        var_press_mode = tk.StringVar(value=clicker.press_mode)
        ttk.Radiobutton(
            press_frame, text="Único", value="Clique único", variable=var_press_mode,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            press_frame, text="Segurar por:", value="Segurar pressionado", variable=var_press_mode,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)
        var_hold_ms = tk.StringVar(value=str(clicker.hold_ms))
        ttk.Entry(press_frame, textvariable=var_hold_ms, width=8).grid(row=1, column=1, padx=4, pady=4)
        ttk.Label(press_frame, text="ms").grid(row=1, column=2, sticky="w")

        interval_frame = ttk.LabelFrame(frm, text="Intervalo entre ações")
        interval_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        row += 1
        ttk.Label(interval_frame, text="Intervalo (ms):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        var_interval_ms = tk.StringVar(value=str(clicker.interval_ms))
        ttk.Entry(interval_frame, textvariable=var_interval_ms, width=10).grid(row=0, column=1, sticky="w", padx=4, pady=4)

        rep_frame = ttk.LabelFrame(frm, text="Quando parar")
        rep_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        row += 1
        var_repeat_mode = tk.StringVar(value=clicker.repeat_mode)
        ttk.Radiobutton(
            rep_frame, text="Até parar manualmente", value="Até parar manualmente", variable=var_repeat_mode,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            rep_frame, text="Número fixo:", value="Número fixo", variable=var_repeat_mode,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)
        var_repeat_count = tk.StringVar(value=str(clicker.repeat_count))
        ttk.Entry(rep_frame, textvariable=var_repeat_count, width=8).grid(row=1, column=1, padx=4, pady=4)
        ttk.Radiobutton(
            rep_frame, text="Duração (s):", value="Por duração", variable=var_repeat_mode,
        ).grid(row=2, column=0, sticky="w", padx=6, pady=4)
        var_duration = tk.StringVar(value=str(clicker.duration_seconds))
        ttk.Entry(rep_frame, textvariable=var_duration, width=8).grid(row=2, column=1, padx=4, pady=4)

        trigger_frame = ttk.LabelFrame(frm, text="Gatilho (tecla ou botão do mouse)")
        trigger_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        row += 1
        var_trigger_label = tk.StringVar(value=f"Gatilho: {trigger_to_label(clicker.trigger)}")
        ttk.Label(trigger_frame, textvariable=var_trigger_label).grid(row=0, column=0, sticky="w", padx=6, pady=4)

        captured_trigger = {"value": clicker.trigger}

        def _on_trigger_captured(trigger):
            captured_trigger["value"] = trigger
            var_trigger_label.set(f"Gatilho: {trigger_to_label(trigger)}")

        def _capture_trigger_click():
            var_trigger_label.set("Pressione uma tecla ou clique com o mouse...")
            self._capture_callback = _on_trigger_captured

        ttk.Button(trigger_frame, text="Definir gatilho...", command=_capture_trigger_click).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )

        var_trigger_mode = tk.StringVar(value=clicker.trigger_mode)
        ttk.Radiobutton(
            trigger_frame, text="Alternar", value="Alternar", variable=var_trigger_mode,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            trigger_frame, text="Segurar para ativar", value="Segurar", variable=var_trigger_mode,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=4)

        var_enabled = tk.BooleanVar(value=clicker.hotkey_enabled)
        ttk.Checkbutton(trigger_frame, text="Gatilho ativado", variable=var_enabled).grid(
            row=2, column=0, sticky="w", padx=6, pady=4
        )

        def _on_save():
            if var_action_kind.get() == "keyboard" and captured_action_key["value"] is None:
                messagebox.showerror("Erro", "Defina uma tecla de ação antes de salvar.")
                return
            if captured_trigger["value"] is None:
                messagebox.showerror("Erro", "Defina um gatilho antes de salvar.")
                return

            clicker.name = var_name.get().strip() or clicker.name
            clicker.action_kind = var_action_kind.get()
            clicker.button = BUTTON_MAP.get(var_button.get(), mouse.Button.left)
            clicker.click_type = var_click_type.get()
            clicker.action_key = captured_action_key["value"]
            clicker.press_mode = var_press_mode.get()
            try:
                clicker.hold_ms = max(0, int(var_hold_ms.get() or 0))
            except ValueError:
                clicker.hold_ms = 50
            try:
                clicker.interval_ms = max(1, float(var_interval_ms.get() or 100))
            except ValueError:
                clicker.interval_ms = 100
            clicker.repeat_mode = var_repeat_mode.get()
            try:
                clicker.repeat_count = max(1, int(var_repeat_count.get() or 10))
            except ValueError:
                clicker.repeat_count = 10
            try:
                clicker.duration_seconds = max(0.1, float(var_duration.get() or 10))
            except ValueError:
                clicker.duration_seconds = 10.0
            clicker.trigger = captured_trigger["value"]
            clicker.trigger_mode = var_trigger_mode.get()
            clicker.hotkey_enabled = var_enabled.get()

            self._refresh_clicker_list()
            self._capture_callback = None
            win.destroy()

        def _on_cancel():
            self._capture_callback = None
            win.destroy()

        action_btns = ttk.Frame(frm)
        action_btns.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(action_btns, text="Salvar", command=_on_save).grid(row=0, column=0, padx=6)
        ttk.Button(action_btns, text="Cancelar", command=_on_cancel).grid(row=0, column=1, padx=6)

        win.protocol("WM_DELETE_WINDOW", _on_cancel)

    def _build_tab_interface(self, tab):
        frame = ttk.LabelFrame(tab, text="Comportamento da janela")
        frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        self.var_sound = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Tocar um som ao iniciar/parar o autoclique", variable=self.var_sound,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)

        self.var_always_on_top = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Manter a janela sempre no topo", variable=self.var_always_on_top,
            command=lambda: self.root.attributes("-topmost", self.var_always_on_top.get()),
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.var_minimize_on_start = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Minimizar a janela automaticamente ao iniciar o autoclique",
            variable=self.var_minimize_on_start,
        ).grid(row=2, column=0, sticky="w", padx=6, pady=4)

        startup_frame = ttk.LabelFrame(tab, text="Inicialização")
        startup_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)

        _cleanup_old_run_value()

        # O estado inicial reflete o registro de verdade (não uma preferência
        # salva à parte), então a caixa nunca fica "desincronizada" da
        # realidade — por exemplo, se o .exe foi movido ou a entrada foi
        # removida por fora do app.
        self.var_run_on_startup = tk.BooleanVar(value=_is_run_on_startup_enabled())
        ttk.Checkbutton(
            startup_frame, text="Iniciar automaticamente ao ligar o Windows (login)",
            variable=self.var_run_on_startup, command=self._on_toggle_run_on_startup,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)

        # Só tem efeito quando o app é aberto pela entrada de inicialização
        # acima — abrir manualmente pelo atalho sempre mostra a janela normal.
        self.var_start_hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            startup_frame, text="Ao iniciar com o Windows, abrir direto oculto na bandeja",
            variable=self.var_start_hidden,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

    def _on_toggle_run_on_startup(self):
        _set_run_on_startup(self.var_run_on_startup.get())

    def _build_tab_perfis(self, tab):
        info = ttk.Label(tab, text="Salve combinações de configurações para reutilizar depois.")
        info.grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 10))

        save_frame = ttk.LabelFrame(tab, text="Salvar configuração atual")
        save_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=6)

        self.var_profile_name = tk.StringVar(value="")
        ttk.Entry(save_frame, textvariable=self.var_profile_name, width=22).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(save_frame, text="Salvar perfil", command=self._save_profile).grid(row=0, column=1, padx=6, pady=6)

        load_frame = ttk.LabelFrame(tab, text="Perfis salvos")
        load_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=6)

        self.var_selected_profile = tk.StringVar(value="")
        self.combo_profiles = ttk.Combobox(
            load_frame, textvariable=self.var_selected_profile, width=22, state="readonly", values=[],
        )
        self.combo_profiles.grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(load_frame, text="Carregar", command=self._load_profile).grid(row=0, column=1, padx=4, pady=6)
        ttk.Button(load_frame, text="Excluir", command=self._delete_profile).grid(row=0, column=2, padx=4, pady=6)

    # ---------- Captura de tecla ----------

    def _start_hotkey_capture(self):
        self.listening_for_hotkey = True
        self.lbl_hotkey.config(text="Pressione uma tecla ou clique com o mouse...")

    def _start_stopkey_capture(self):
        self.listening_for_stopkey = True
        self.lbl_stop_key.config(text="Pressione uma tecla ou clique com o mouse...")

    def _capture_trigger(self, trigger):
        """Usado pelo teclado e pelo mouse para definir um novo gatilho ou
        uma nova tecla de ação, tanto para o clicker principal quanto para
        os diálogos de edição dos clickers extras (aba "Múltiplos")."""
        if self.listening_for_hotkey:
            self.listening_for_hotkey = False
            self.hotkey = trigger
            self.root.after(0, lambda: self.lbl_hotkey.config(text=f"Tecla atual: {trigger_to_label(trigger)}"))
            return True
        if self.listening_for_stopkey:
            self.listening_for_stopkey = False
            self.stop_key = trigger
            self.root.after(0, lambda: self.lbl_stop_key.config(text=f"Tecla atual: {trigger_to_label(trigger)}"))
            return True
        if self.listening_for_action_key:
            if trigger[0] != "keyboard":
                # A ação de teclado só aceita teclas; ignora cliques de mouse
                # sem cancelar a captura, para não atrapalhar quem clicou em
                # outro lugar por engano enquanto define a tecla.
                return False
            self.listening_for_action_key = False
            self.action_key = trigger[1]
            self.root.after(0, lambda: self.lbl_action_key.config(text=f"Tecla: {key_to_label(trigger[1])}"))
            return True
        if self._capture_callback is not None:
            callback = self._capture_callback
            self._capture_callback = None
            self.root.after(0, callback, trigger)
            return True
        return False

    def _handle_trigger_event(self, trigger, pressed):
        """Chamado (na thread principal, via root.after) a cada tecla ou
        clique do mouse fora do modo de captura. Roteia para o clicker
        principal e para cada clicker extra cujo gatilho bata."""
        if self.stop_key is not None and triggers_equal(trigger, self.stop_key):
            if pressed:
                if self.running:
                    self.stop()
                for c in self.clickers:
                    c.stop()
            return

        if self.var_hotkeys_enabled.get() and triggers_equal(trigger, self.hotkey):
            if self.var_hotkey_mode.get() == "Segurar":
                self.start() if pressed else self.stop()
            elif pressed:
                self.toggle()

        for c in self.clickers:
            if c.hotkey_enabled and triggers_equal(trigger, c.trigger):
                if c.trigger_mode == "Segurar":
                    c.start() if pressed else c.stop()
                elif pressed:
                    c.toggle()

    def _on_key_press(self, key):
        """Usado apenas no modo de fallback (pynput.Listener), quando o hook
        de teclado de baixo nível não pôde ser instalado."""
        trigger = ("keyboard", key)
        if self._capture_trigger(trigger):
            return
        # Le variaveis do Tkinter, entao precisa rodar na thread principal.
        self.root.after(0, self._handle_trigger_event, trigger, True)

    def _on_key_release(self, key):
        self.root.after(0, self._handle_trigger_event, ("keyboard", key), False)

    def _install_input_hooks(self):
        """Instala os hooks globais de mouse e teclado (WH_MOUSE_LL e
        WH_KEYBOARD_LL) numa única thread dedicada com seu próprio loop de
        mensagens (exigido pela API do Windows para hooks de baixo nível).
        Retorna (mouse_ok, keyboard_ok)."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        def _mouse_proc(nCode, wParam, lParam):
            try:
                if nCode == HC_ACTION and wParam in (
                    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP,
                    WM_MBUTTONDOWN, WM_MBUTTONUP, WM_XBUTTONDOWN, WM_XBUTTONUP,
                ):
                    info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    if info.dwExtraInfo != AUTOCLICK_INPUT_TAG:
                        if wParam in _MOUSE_HOOK_BUTTONS:
                            button, pressed = _MOUSE_HOOK_BUTTONS[wParam]
                        else:
                            xbtn = (info.mouseData >> 16) & 0xFFFF
                            button = mouse.Button.x1 if xbtn == XBUTTON1 else mouse.Button.x2
                            pressed = wParam == WM_XBUTTONDOWN
                        self.root.after(0, self._handle_mouse_event, button, pressed)
            except Exception:
                pass
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        def _kb_proc(nCode, wParam, lParam):
            try:
                if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                    info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if info.dwExtraInfo != AUTOCLICK_INPUT_TAG:
                        key = _vk_event_to_key(info.vkCode, info.scanCode)
                        if key is not None:
                            pressed = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                            self.root.after(0, self._handle_key_event, key, pressed)
            except Exception:
                pass
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        # Mantém referência forte aos callbacks: se fossem coletados pelo GC,
        # o Windows chamaria um ponteiro de função morto.
        self._mouse_hook_proc_ref = LowLevelMouseProc(_mouse_proc)
        self._kb_hook_proc_ref = LowLevelKeyboardProc(_kb_proc)

        ready = threading.Event()
        result = {"mouse": False, "kb": False}

        def _thread_main():
            hmod = kernel32.GetModuleHandleW(None)
            mouse_id = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_hook_proc_ref, hmod, 0)
            kb_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_hook_proc_ref, hmod, 0)
            self._hook_mouse_id = mouse_id
            self._hook_kb_id = kb_id
            self._hook_thread_id = kernel32.GetCurrentThreadId()
            result["mouse"] = bool(mouse_id)
            result["kb"] = bool(kb_id)
            ready.set()
            if not mouse_id and not kb_id:
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if mouse_id:
                user32.UnhookWindowsHookEx(mouse_id)
            if kb_id:
                user32.UnhookWindowsHookEx(kb_id)

        self._hook_thread = threading.Thread(target=_thread_main, daemon=True)
        self._hook_thread.start()
        ready.wait(timeout=2.0)
        return result["mouse"], result["kb"]

    def _handle_mouse_event(self, button, pressed):
        """Chamado (já na thread principal, via root.after) para cada clique
        REAL do mouse detectado pelo hook — os sintéticos já foram filtrados
        antes de chegar aqui, então não há mais nada para "descontar"."""
        trigger = ("mouse", button)
        if pressed and self._capture_trigger(trigger):
            return
        self._handle_trigger_event(trigger, pressed)

    def _handle_key_event(self, key, pressed):
        """Chamado (já na thread principal, via root.after) para cada tecla
        REAL detectada pelo hook — os pressionamentos sintéticos (ação de
        teclado do autoclique) já vêm filtrados antes de chegar aqui."""
        trigger = ("keyboard", key)
        if pressed and self._capture_trigger(trigger):
            return
        self._handle_trigger_event(trigger, pressed)

    def _on_mouse_click(self, x, y, button, pressed):
        """Usado apenas no modo de fallback (pynput.Listener), quando o hook
        de baixo nível não pôde ser instalado."""
        with self.echo_lock:
            if button == self.echo_button and self.pending_echo_count > 0:
                self.pending_echo_count -= 1
                return
        trigger = ("mouse", button)
        if pressed and self._capture_trigger(trigger):
            return
        self.root.after(0, self._handle_trigger_event, trigger, pressed)

    # ---------- Captura de posição ----------

    def _start_capture_position(self):
        if self.capturing_pos:
            return
        self.capturing_pos = True
        self._countdown_capture(3)

    def _countdown_capture(self, seconds_left):
        if seconds_left <= 0:
            pos = self.mouse_ctrl.position
            self.fixed_pos = pos
            self.lbl_fixed_pos.config(text=f"x={pos[0]}, y={pos[1]}")
            self.var_position_mode.set("Posição fixa")
            self.capturing_pos = False
            self._refresh_marker()
            return
        self.lbl_fixed_pos.config(text=f"capturando em {seconds_left}...")
        self.root.after(1000, lambda: self._countdown_capture(seconds_left - 1))

    # ---------- Indicador visual ----------

    def _pick_marker_color(self):
        result = colorchooser.askcolor(color=self.var_marker_color.get() or "#facc15", title="Cor do indicador")
        if result and result[1]:
            self.var_marker_color.set(result[1])
            self._refresh_marker()

    def _refresh_marker(self):
        show = (
            self.var_show_marker.get()
            and self.var_position_mode.get() == "Posição fixa"
            and self.fixed_pos is not None
        )
        if not show:
            if self.marker_window is not None:
                self.marker_window.destroy()
                self.marker_window = None
                self.marker_canvas = None
            return

        size = 44
        x, y = self.fixed_pos
        color = self.var_marker_color.get() or "#facc15"

        if self.marker_window is None:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            transparent = MARKER_TRANSPARENT_COLOR
            win.configure(bg=transparent)
            try:
                win.attributes("-transparentcolor", transparent)
            except tk.TclError:
                pass
            canvas = tk.Canvas(win, width=size, height=size, bg=transparent, highlightthickness=0)
            canvas.pack()
            self.marker_window = win
            self.marker_canvas = canvas
            win.update_idletasks()
            self._make_clickthrough(win)

        self.marker_window.geometry(f"{size}x{size}+{x - size // 2}+{y - size // 2}")
        canvas = self.marker_canvas
        canvas.delete("all")
        canvas.create_oval(4, 4, size - 4, size - 4, outline=color, width=2)
        canvas.create_line(size // 2, 0, size // 2, size, fill=color, width=1)
        canvas.create_line(0, size // 2, size, size // 2, fill=color, width=1)

    @staticmethod
    def _make_clickthrough(win):
        # Faz o indicador ser puramente visual: os cliques do autoclique
        # (e do usuário) atravessam a janela e chegam no que está atrás dela.
        try:
            hwnd = win.winfo_id()
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            # SetWindowLongW reseta a cor-chave configurada pelo Tk via
            # "-transparentcolor" (senão a janela vira um retângulo preto
            # sólido) — reaplica com SetLayeredWindowAttributes.
            user32.SetLayeredWindowAttributes(hwnd, MARKER_COLORKEY, 0, LWA_COLORKEY)
        except Exception:
            pass

    # ---------- Início/parada ----------

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.running:
            return

        try:
            interval = self._get_interval_seconds()
        except ValueError:
            messagebox.showerror("Erro", "Valores de intervalo inválidos.")
            return
        if interval <= 0:
            messagebox.showerror("Erro", "O intervalo precisa ser maior que zero.")
            return

        if self.var_action_kind.get() == "keyboard":
            if self.action_key is None:
                messagebox.showerror("Erro", "Defina uma tecla para a ação antes de iniciar.")
                return
        elif self.var_position_mode.get() == "Posição fixa" and not self.fixed_pos:
            messagebox.showerror("Erro", "Capture uma posição fixa antes de iniciar.")
            return

        repeat_count = None
        duration_seconds = None
        mode = self.var_repeat_mode.get()
        if mode == "Número fixo":
            try:
                repeat_count = int(self.var_repeat_count.get())
            except ValueError:
                messagebox.showerror("Erro", "Número de cliques inválido.")
                return
            if repeat_count <= 0:
                messagebox.showerror("Erro", "O número de cliques precisa ser maior que zero.")
                return
        elif mode == "Por duração":
            try:
                dh = float(self.var_dur_h.get() or 0)
                dm = float(self.var_dur_m.get() or 0)
                ds = float(self.var_dur_s.get() or 0)
            except ValueError:
                messagebox.showerror("Erro", "Duração inválida.")
                return
            duration_seconds = dh * 3600 + dm * 60 + ds
            if duration_seconds <= 0:
                messagebox.showerror("Erro", "A duração precisa ser maior que zero.")
                return

        try:
            start_delay = max(0.0, float(self.var_start_delay.get() or 0))
        except ValueError:
            start_delay = 0.0

        if self.var_minimize_on_start.get():
            self.root.iconify()
        if self.var_sound.get():
            self._beep(880)

        self.running = True
        self.click_count = 0
        self.stop_now_event.clear()
        self.lbl_status.config(text="Rodando", foreground="green")
        self.btn_toggle.config(text="Parar (ou pressione a tecla)")

        # Acorda a thread de trabalho persistente para este ciclo (ver
        # comentário em __init__ sobre por que não criamos uma thread nova
        # aqui). "run_event" é lido pelo "_worker_loop".
        self.run_params = (start_delay, interval, repeat_count, duration_seconds)
        self.run_event.set()

    def _worker_loop(self):
        while True:
            self.run_event.wait()
            if self.shutting_down:
                return
            self.run_event.clear()
            start_delay, interval, repeat_count, duration_seconds = self.run_params
            if start_delay > 0 and self.stop_now_event.wait(start_delay):
                self.root.after(0, self.stop)
                continue
            self._click_loop(interval, repeat_count, duration_seconds)

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.stop_now_event.set()
        self.lbl_status.config(text="Parado", foreground="red")
        self.btn_toggle.config(text="Iniciar (ou pressione a tecla)")
        if self.var_sound.get():
            self._beep(440)

    def _beep(self, freq):
        if winsound is None:
            return

        def _play():
            try:
                winsound.Beep(freq, 120)
            except Exception:
                pass

        # winsound.Beep bloqueia pela duração do som; como start()/stop() são
        # chamados na thread principal (inclusive várias vezes por segundo no
        # modo "segurar"), tocar direto aqui travaria a interface a cada
        # toque. Dispara numa thread solta em vez disso.
        threading.Thread(target=_play, daemon=True).start()

    def _get_interval_seconds(self):
        h = float(self.var_h.get() or 0)
        m = float(self.var_m.get() or 0)
        s = float(self.var_s.get() or 0)
        ms = float(self.var_ms.get() or 0)
        return h * 3600 + m * 60 + s + ms / 1000.0

    def _click_loop(self, interval, repeat_count, duration_seconds):
        action_kind = self.var_action_kind.get()
        button = BUTTON_MAP[self.var_button.get()]
        click_count = CLICK_TYPE_COUNT[self.var_click_type.get()]
        action_key = self.action_key
        hold_mode = self.var_press_mode.get() == "Segurar pressionado"
        try:
            hold_seconds = max(0, int(self.var_hold_ms.get() or 0)) / 1000.0
        except ValueError:
            hold_seconds = 0.0

        use_fixed = action_kind == "mouse" and self.var_position_mode.get() == "Posição fixa"
        fixed_pos = self.fixed_pos
        random_pos = self.var_random_pos.get()
        try:
            pos_radius = max(0, int(self.var_pos_radius.get() or 0))
        except ValueError:
            pos_radius = 0

        random_interval = self.var_random_interval.get()
        try:
            jitter_min = max(0.0, float(self.var_jitter_min.get() or 0)) / 1000.0
            jitter_max = max(jitter_min, float(self.var_jitter_max.get() or 0) / 1000.0)
        except ValueError:
            jitter_min = jitter_max = 0.0

        return_pos = self.var_return_pos.get()
        action_vk, action_scan = _key_to_vk_scan(action_key) if action_kind == "keyboard" else (None, None)

        start_time = time.time()
        done = 0
        last_ui_update = 0.0
        while not self.stop_now_event.is_set():
            wait_time = interval
            if random_interval:
                wait_time += random.uniform(jitter_min, jitter_max)
            if self.stop_now_event.wait(wait_time):
                break

            if duration_seconds is not None and (time.time() - start_time) >= duration_seconds:
                self.root.after(0, self.stop)
                break

            if action_kind == "keyboard":
                if action_vk is not None:
                    if hold_mode:
                        _send_key(action_vk, action_scan, True)
                        time.sleep(hold_seconds)
                        _send_key(action_vk, action_scan, False)
                    else:
                        _send_key(action_vk, action_scan, True)
                        _send_key(action_vk, action_scan, False)
            else:
                original_pos = self.mouse_ctrl.position
                target_pos = fixed_pos if use_fixed and fixed_pos else None
                if target_pos and random_pos and pos_radius > 0:
                    angle = random.uniform(0, 2 * math.pi)
                    r = random.uniform(0, pos_radius)
                    target_pos = (
                        int(target_pos[0] + r * math.cos(angle)),
                        int(target_pos[1] + r * math.sin(angle)),
                    )
                if target_pos:
                    self.mouse_ctrl.position = target_pos

                # Só precisa do sistema antigo de crédito por contagem quando
                # o hook de baixo nível (WH_MOUSE_LL) não pôde ser instalado
                # — com ele ativo, os cliques sintéticos já chegam marcados
                # com AUTOCLICK_INPUT_TAG e nunca passam pelo listener, então
                # não há nada para descontar.
                if not self._using_raw_mouse_hook:
                    expected_events = 2 if hold_mode else 2 * click_count
                    with self.echo_lock:
                        self.echo_button = button
                        self.pending_echo_count += expected_events

                if hold_mode:
                    _send_mouse_button(button, True)
                    time.sleep(hold_seconds)
                    _send_mouse_button(button, False)
                else:
                    _synthetic_click(button, click_count)

                if return_pos and target_pos:
                    self.mouse_ctrl.position = original_pos

            done += 1
            is_last = repeat_count is not None and done >= repeat_count
            now_ts = time.time()
            # Com intervalos bem curtos, agendar uma atualização de tela a
            # cada clique enche a fila de eventos do Tkinter e pode causar
            # engasgos perceptíveis na interface (e atrasar a reação a
            # teclas/botões). Atualiza no máximo ~20x por segundo, sempre
            # garantindo o valor final exato.
            if is_last or now_ts - last_ui_update >= 0.05:
                last_ui_update = now_ts
                self.root.after(0, self._update_count, done)

            if is_last:
                self.root.after(0, self.stop)
                break

    def _update_count(self, count):
        self.click_count = count
        self.lbl_count.config(text=f"Cliques: {count}")

    # ---------- Atualizações ----------

    def _check_for_update(self, manual):
        """Roda numa thread solta (nunca trava a UI). Só baixa algo se a
        release publicada for realmente mais nova que a versão atual."""
        if not getattr(sys, "frozen", False):
            if manual:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Atualizações", "A verificação de atualizações só funciona no .exe empacotado."
                ))
            return
        try:
            release = _fetch_latest_release()
            latest_version = _parse_version(release.get("tag_name", ""))
            if latest_version <= _parse_version(APP_VERSION):
                if manual:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Atualizações", f"Você já está na versão mais recente ({APP_VERSION})."
                    ))
                return
            asset = next(
                (a for a in release.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None
            )
            if asset is None:
                return
            exe_path = sys.executable
            new_path = exe_path + ".update"
            req = urllib.request.Request(
                asset["browser_download_url"], headers={"User-Agent": f"{APP_NAME}-updater"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp, open(new_path, "wb") as f:
                f.write(resp.read())
            if os.path.getsize(new_path) < 1024:
                os.remove(new_path)
                return
            self._pending_update_path = new_path
            tag = release.get("tag_name", "?")
            try:
                self.tray_icon.notify(
                    f"Versão {tag} baixada — será aplicada da próxima vez que o {APP_NAME} fechar.",
                    APP_NAME,
                )
            except Exception:
                pass
            if manual:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Atualizações", f"Versão {tag} baixada. Será instalada ao fechar o {APP_NAME}."
                ))
        except Exception:
            if manual:
                self.root.after(0, lambda: messagebox.showerror(
                    "Atualizações", "Não foi possível verificar atualizações agora. Tente de novo mais tarde."
                ))

    def _apply_pending_update(self):
        """Dispara um script auxiliar que espera este processo encerrar,
        troca o .exe pela versão baixada e reabre o app — assim a troca
        nunca mexe num arquivo que ainda está em execução."""
        exe_path = sys.executable
        pid = os.getpid()
        bat_path = self._pending_update_path + ".bat"
        script = (
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
            "if not errorlevel 1 (\r\n"
            "    timeout /t 1 /nobreak >nul\r\n"
            "    goto wait\r\n"
            ")\r\n"
            f'move /y "{self._pending_update_path}" "{exe_path}"\r\n'
            f'start "" "{exe_path}"\r\n'
            'del "%~f0"\r\n'
        )
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        except OSError:
            pass

    # ---------- Bandeja do sistema ----------

    def _hide_to_tray(self):
        """Chamado ao clicar no X da janela: esconde em vez de fechar, para
        o autoclique, os atalhos e a bandeja continuarem funcionando."""
        self.root.withdraw()
        if not self._notified_background:
            self._notified_background = True
            try:
                self.tray_icon.notify(
                    f"O {APP_NAME} continua rodando em segundo plano. Clique no ícone da bandeja para abrir de novo.",
                    APP_NAME,
                )
            except Exception:
                pass

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, self._show_window)

    def _tray_toggle(self, icon=None, item=None):
        self.root.after(0, self.toggle)

    def _tray_check_updates(self, icon=None, item=None):
        threading.Thread(target=self._check_for_update, args=(True,), daemon=True).start()

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self._quit_app)

    def _quit_app(self):
        """Fecha o app de verdade (só acessível pelo menu da bandeja)."""
        if self._pending_update_path and os.path.isfile(self._pending_update_path):
            self._apply_pending_update()
        self._save_config()
        self.shutting_down = True
        self.stop_now_event.set()
        self.run_event.set()
        for c in self.clickers:
            c.shutting_down = True
            c.stop_now_event.set()
            c.run_event.set()
        if self.kb_listener is not None:
            self.kb_listener.stop()
        if self.mouse_listener is not None:
            self.mouse_listener.stop()
        if (self._using_raw_mouse_hook or self._using_raw_kb_hook) and self._hook_thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        self.tray_icon.stop()
        if self.lock_socket is not None:
            try:
                self.lock_socket.close()
            except OSError:
                pass
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self.root.destroy()

    def start_show_request_listener(self, lock_socket):
        """Escuta na mesma porta da trava de instância única: quando o
        usuário tenta abrir o .exe de novo (ex: pelo atalho) enquanto já há
        uma instância rodando (talvez escondida na bandeja), essa segunda
        tentativa avisa aqui em vez de só mostrar um aviso e não fazer nada —
        trazemos a janela existente de volta."""
        self.lock_socket = lock_socket

        def _serve():
            while True:
                try:
                    conn, _ = lock_socket.accept()
                except OSError:
                    return
                try:
                    conn.recv(16)
                except OSError:
                    pass
                finally:
                    conn.close()
                self.root.after(0, self._show_window)

        threading.Thread(target=_serve, daemon=True).start()

    # ---------- Configurações persistentes ----------

    def _gather_config_dict(self):
        return {
            "h": self.var_h.get(), "m": self.var_m.get(), "s": self.var_s.get(), "ms": self.var_ms.get(),
            "action_kind": self.var_action_kind.get(),
            "action_key": _serialize_key(self.action_key),
            "button": self.var_button.get(),
            "click_type": self.var_click_type.get(),
            "press_mode": self.var_press_mode.get(),
            "hold_ms": self.var_hold_ms.get(),
            "random_interval": self.var_random_interval.get(),
            "jitter_min": self.var_jitter_min.get(),
            "jitter_max": self.var_jitter_max.get(),
            "position_mode": self.var_position_mode.get(),
            "fixed_pos": list(self.fixed_pos) if self.fixed_pos else None,
            "random_pos": self.var_random_pos.get(),
            "pos_radius": self.var_pos_radius.get(),
            "show_marker": self.var_show_marker.get(),
            "marker_color": self.var_marker_color.get(),
            "return_pos": self.var_return_pos.get(),
            "repeat_mode": self.var_repeat_mode.get(),
            "repeat_count": self.var_repeat_count.get(),
            "dur_h": self.var_dur_h.get(), "dur_m": self.var_dur_m.get(), "dur_s": self.var_dur_s.get(),
            "start_delay": self.var_start_delay.get(),
            "hotkey": _serialize_trigger(self.hotkey),
            "hotkey_mode": self.var_hotkey_mode.get(),
            "stop_key": _serialize_trigger(self.stop_key),
            "hotkeys_enabled": self.var_hotkeys_enabled.get(),
            "sound": self.var_sound.get(),
            "always_on_top": self.var_always_on_top.get(),
            "minimize_on_start": self.var_minimize_on_start.get(),
            "start_hidden": self.var_start_hidden.get(),
            "clickers": [c.to_dict() for c in self.clickers],
        }

    def _apply_config_dict(self, data):
        def g(key, var):
            var.set(data.get(key, var.get()))

        g("h", self.var_h); g("m", self.var_m); g("s", self.var_s); g("ms", self.var_ms)
        g("action_kind", self.var_action_kind)
        g("button", self.var_button)
        g("click_type", self.var_click_type)
        g("press_mode", self.var_press_mode)
        g("hold_ms", self.var_hold_ms)
        g("random_interval", self.var_random_interval)
        g("jitter_min", self.var_jitter_min)
        g("jitter_max", self.var_jitter_max)
        g("position_mode", self.var_position_mode)
        g("random_pos", self.var_random_pos)
        g("pos_radius", self.var_pos_radius)
        g("show_marker", self.var_show_marker)
        g("marker_color", self.var_marker_color)
        g("return_pos", self.var_return_pos)
        g("repeat_mode", self.var_repeat_mode)
        g("repeat_count", self.var_repeat_count)
        g("dur_h", self.var_dur_h); g("dur_m", self.var_dur_m); g("dur_s", self.var_dur_s)
        g("start_delay", self.var_start_delay)
        g("hotkey_mode", self.var_hotkey_mode)
        g("hotkeys_enabled", self.var_hotkeys_enabled)
        g("sound", self.var_sound)
        g("always_on_top", self.var_always_on_top)
        g("minimize_on_start", self.var_minimize_on_start)
        g("start_hidden", self.var_start_hidden)

        fixed_pos = data.get("fixed_pos")
        if fixed_pos and len(fixed_pos) == 2:
            self.fixed_pos = tuple(fixed_pos)
            self.lbl_fixed_pos.config(text=f"x={fixed_pos[0]}, y={fixed_pos[1]}")
        else:
            self.fixed_pos = None
            self.lbl_fixed_pos.config(text="não definida")

        trigger = _deserialize_trigger(data.get("hotkey"))
        if trigger is not None:
            self.hotkey = trigger
            self.lbl_hotkey.config(text=f"Tecla atual: {trigger_to_label(trigger)}")

        self.stop_key = _deserialize_trigger(data.get("stop_key"))
        self.lbl_stop_key.config(text=f"Tecla atual: {trigger_to_label(self.stop_key)}")

        self.action_key = _deserialize_key(data.get("action_key"))
        self.lbl_action_key.config(text=f"Tecla: {key_to_label(self.action_key)}")
        self._refresh_action_kind_state()

        clickers_data = data.get("clickers")
        if clickers_data is not None:
            for c in self.clickers:
                c.shutting_down = True
                c.stop_now_event.set()
                c.run_event.set()
            self.clickers = []
            for cd in clickers_data:
                c = ClickerInstance(self)
                c.load_dict(cd)
                self.clickers.append(c)
            if hasattr(self, "tree_clickers"):
                self._refresh_clicker_list()

        self.root.attributes("-topmost", self.var_always_on_top.get())
        self._refresh_marker()

    def _load_config(self):
        try:
            with open(_config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        self._apply_config_dict(data)

    def _save_config(self):
        try:
            with open(_config_path(), "w", encoding="utf-8") as f:
                json.dump(self._gather_config_dict(), f)
        except OSError:
            pass

    # ---------- Perfis ----------

    def _load_profiles(self):
        try:
            with open(_profiles_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_profiles(self, profiles):
        try:
            with open(_profiles_path(), "w", encoding="utf-8") as f:
                json.dump(profiles, f)
        except OSError:
            pass

    def _refresh_profile_list(self):
        names = sorted(self._load_profiles().keys())
        self.combo_profiles["values"] = names
        if names and self.var_selected_profile.get() not in names:
            self.var_selected_profile.set(names[0])

    def _save_profile(self):
        name = self.var_profile_name.get().strip()
        if not name:
            messagebox.showerror("Erro", "Digite um nome para o perfil.")
            return
        profiles = self._load_profiles()
        profiles[name] = self._gather_config_dict()
        self._save_profiles(profiles)
        self.var_profile_name.set("")
        self._refresh_profile_list()
        self.var_selected_profile.set(name)
        messagebox.showinfo("Perfis", f'Perfil "{name}" salvo.')

    def _load_profile(self):
        name = self.var_selected_profile.get()
        profiles = self._load_profiles()
        if name not in profiles:
            messagebox.showerror("Erro", "Selecione um perfil válido.")
            return
        self._apply_config_dict(profiles[name])

    def _delete_profile(self):
        name = self.var_selected_profile.get()
        profiles = self._load_profiles()
        if name in profiles:
            del profiles[name]
            self._save_profiles(profiles)
            self.var_selected_profile.set("")
            self._refresh_profile_list()
            messagebox.showinfo("Perfis", f'Perfil "{name}" excluído.')


class ClickerInstance:
    """Um autoclique adicional e independente, criado e gerenciado pela aba
    "Múltiplos". Cada instância tem sua própria configuração, gatilho e
    thread de trabalho persistente, e roda em paralelo com o clicker
    principal e com os demais — start/stop de um nunca afeta os outros."""

    _next_num = 1

    def __init__(self, app):
        self.app = app
        self.name = f"Clicker {ClickerInstance._next_num}"
        ClickerInstance._next_num += 1

        self.action_kind = "mouse"  # "mouse" ou "keyboard"
        self.button = mouse.Button.left
        self.click_type = "Simples"
        self.action_key = None

        self.press_mode = "Clique único"
        self.hold_ms = 50

        self.interval_ms = 100.0
        self.repeat_mode = "Até parar manualmente"
        self.repeat_count = 10
        self.duration_seconds = 10.0
        self.start_delay = 0.0

        self.trigger = None
        self.trigger_mode = "Alternar"
        self.hotkey_enabled = True

        self.running = False
        self.click_count = 0
        self.run_event = threading.Event()
        self.stop_now_event = threading.Event()
        self.shutting_down = False
        self._run_params = None
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def action_label(self):
        if self.action_kind == "keyboard":
            return f"Tecla {key_to_label(self.action_key)}" if self.action_key else "Tecla (não definida)"
        label = next((k for k, v in BUTTON_MAP.items() if v == self.button), "Esquerdo")
        return f"Mouse {label} ({self.click_type})"

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        if self.running:
            return
        if self.action_kind == "keyboard" and self.action_key is None:
            return
        interval = max(0.001, self.interval_ms / 1000.0)
        repeat_count = self.repeat_count if self.repeat_mode == "Número fixo" else None
        duration = self.duration_seconds if self.repeat_mode == "Por duração" else None

        self.running = True
        self.click_count = 0
        self.stop_now_event.clear()
        self.app.root.after(0, self.app._refresh_clicker_list)

        self._run_params = (self.start_delay, interval, repeat_count, duration)
        self.run_event.set()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.stop_now_event.set()
        self.app.root.after(0, self.app._refresh_clicker_list)

    def _worker_loop(self):
        while True:
            self.run_event.wait()
            if self.shutting_down:
                return
            self.run_event.clear()
            start_delay, interval, repeat_count, duration = self._run_params
            if start_delay > 0 and self.stop_now_event.wait(start_delay):
                self.app.root.after(0, self.stop)
                continue
            self._click_loop(interval, repeat_count, duration)

    def _click_loop(self, interval, repeat_count, duration_seconds):
        hold_mode = self.press_mode == "Segurar pressionado"
        hold_seconds = max(0, self.hold_ms) / 1000.0
        click_count = CLICK_TYPE_COUNT.get(self.click_type, 1) if self.action_kind == "mouse" else 1
        action_vk, action_scan = _key_to_vk_scan(self.action_key) if self.action_kind == "keyboard" else (None, None)

        start_time = time.time()
        done = 0
        last_ui_update = 0.0
        while not self.stop_now_event.is_set():
            if self.stop_now_event.wait(interval):
                break
            if duration_seconds is not None and (time.time() - start_time) >= duration_seconds:
                self.app.root.after(0, self.stop)
                break

            if self.action_kind == "keyboard":
                if action_vk is not None:
                    if hold_mode:
                        _send_key(action_vk, action_scan, True)
                        time.sleep(hold_seconds)
                        _send_key(action_vk, action_scan, False)
                    else:
                        _send_key(action_vk, action_scan, True)
                        _send_key(action_vk, action_scan, False)
            else:
                if hold_mode:
                    _send_mouse_button(self.button, True)
                    time.sleep(hold_seconds)
                    _send_mouse_button(self.button, False)
                else:
                    _synthetic_click(self.button, click_count)

            done += 1
            is_last = repeat_count is not None and done >= repeat_count
            now_ts = time.time()
            if is_last or now_ts - last_ui_update >= 0.1:
                last_ui_update = now_ts
                self.click_count = done
                self.app.root.after(0, self.app._refresh_clicker_list)
            if is_last:
                self.app.root.after(0, self.stop)
                break

    def to_dict(self):
        return {
            "name": self.name,
            "action_kind": self.action_kind,
            "button": self.button.name,
            "click_type": self.click_type,
            "action_key": _serialize_key(self.action_key),
            "press_mode": self.press_mode,
            "hold_ms": self.hold_ms,
            "interval_ms": self.interval_ms,
            "repeat_mode": self.repeat_mode,
            "repeat_count": self.repeat_count,
            "duration_seconds": self.duration_seconds,
            "start_delay": self.start_delay,
            "trigger": _serialize_trigger(self.trigger),
            "trigger_mode": self.trigger_mode,
            "hotkey_enabled": self.hotkey_enabled,
        }

    def load_dict(self, data):
        self.name = data.get("name", self.name)
        self.action_kind = data.get("action_kind", "mouse")
        try:
            self.button = mouse.Button[data.get("button", "left")]
        except KeyError:
            self.button = mouse.Button.left
        self.click_type = data.get("click_type", "Simples")
        self.action_key = _deserialize_key(data.get("action_key"))
        self.press_mode = data.get("press_mode", "Clique único")
        self.hold_ms = data.get("hold_ms", 50)
        self.interval_ms = data.get("interval_ms", 100.0)
        self.repeat_mode = data.get("repeat_mode", "Até parar manualmente")
        self.repeat_count = data.get("repeat_count", 10)
        self.duration_seconds = data.get("duration_seconds", 10.0)
        self.start_delay = data.get("start_delay", 0.0)
        self.trigger = _deserialize_trigger(data.get("trigger"))
        self.trigger_mode = data.get("trigger_mode", "Alternar")
        self.hotkey_enabled = data.get("hotkey_enabled", True)


def main():
    # Trava de instância única: evita duas janelas e dois hotkeys globais
    # brigando pelo mesmo toggle caso o .exe seja aberto duas vezes. A mesma
    # porta também serve para uma segunda tentativa avisar a instância que já
    # está rodando (possivelmente escondida na bandeja) para trazer a janela
    # de volta, em vez de só mostrar "já está em execução" e não fazer nada.
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", _SINGLE_INSTANCE_PORT), timeout=1) as s:
                s.sendall(b"show")
        except OSError:
            pass
        sys.exit(0)

    lock_socket.listen(4)

    # Por padrão o Windows só garante ~15.6ms de precisão para temporizadores
    # (sleep, wait com timeout etc). Isso faz intervalos bem curtos (poucos
    # milissegundos) não serem respeitados de verdade — o clique acaba saindo
    # bem mais devagar do que o configurado. Pedimos resolução de 1ms para o
    # processo inteiro, o mesmo truque usado por jogos e ferramentas que
    # precisam de temporização fina.
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

    # A entrada de "iniciar com o Windows" chama o .exe com essa flag (veja
    # _startup_command), o que permite diferenciar esse tipo de abertura de
    # um clique manual no atalho — só quando vem daqui que a opção "iniciar
    # oculto" (aba Interface) tem efeito.
    launched_via_startup = "--startup" in sys.argv[1:]

    root = tk.Tk()
    if launched_via_startup:
        # Evita o "flash" da janela aparecendo e sumindo logo em seguida
        # quando o app já vai nascer escondido na bandeja.
        root.withdraw()
    app = AutoClickerApp(root, launched_via_startup=launched_via_startup)
    app.start_show_request_listener(lock_socket)
    root.mainloop()


if __name__ == "__main__":
    main()
