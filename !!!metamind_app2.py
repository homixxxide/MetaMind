# MetaMind v6.0
# ВЫШЛА
# 5.5
# Changelog:
# - Enter для добавления героя (если в списке 1 результат)
# - Окно "Что нового" при первом запуске новой версии
# - Улучшена стабильность OpenDota
#
# v5.5:
# - Главное окно теперь ПОВЕРХ всех приложений (показывается поверх игры)
# - Исправлен OpenDota API с множественными fallback
# - Добавлены статические данные при недоступности API
# - FloatingIcon: полностью прозрачная, только буква "M" (без фона/обводки)
# - Убрана кнопка сворачивания из хедера (функция hide/show перенесена в FloatingIcon)
# - Кнопка "Обновить данные": белый текст
# - Fix: бесконечная загрузка при ручном обновлении OpenDota (UI callback через Qt Signal)
# - Refresh strategy: быстрый старт из кэша + обновление в фоне; при открытии страницы "Мета" автопроверка обновления

from __future__ import annotations

import sys
import os
import json
import time
import threading
import requests
import certifi
from io import BytesIO
import ctypes

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QListWidget, QListWidgetItem, QFrame,
    QSpacerItem, QSizePolicy, QStackedWidget, QComboBox,
    QDialog, QSplitter, QSizeGrip, QAbstractItemView
)
from PySide6.QtCore import (
    Qt, QSize, QPoint, QPropertyAnimation,
    QEasingCurve, QRect, QTimer, QCoreApplication,
    QObject, Signal
)
from PySide6.QtGui import QFont, QIcon, QPixmap, QMouseEvent, QCloseEvent
import winsound
import base64
from io import BytesIO
from PIL import ImageGrab
import cv2
import numpy as np
from PIL import Image
# ================= GSI SERVER INTEGRATION =================
import string
from flask import Flask, request, jsonify


class GSIServer:
    """Встроенный GSI сервер для MetaMind"""

    def __init__(self):
        self.app = Flask(__name__)
        self.app.logger.disabled = True  # Отключаем логи Flask

        self.game_in_progress = False
        self.last_game_state = None
        self.player_team = None
        self.game_time = 0
        self.last_update = 0

        self.setup_routes()
        self.auto_setup_gsi()

    def setup_routes(self):
        """Настройка Flask endpoints"""

        @self.app.route('/', methods=['POST'])
        def gsi_endpoint():
            try:
                data = request.json
                if not data:
                    return "No data", 400

                self.last_update = time.time()

                # Команда игрока
                player_data = data.get("player", {})
                team = player_data.get("team_name", "").lower()

                if team and not self.player_team:
                    if 'radiant' in team:
                        self.player_team = 'radiant'
                        print(f"[GSI] ✅ RADIANT (слева)")
                    elif 'dire' in team:
                        self.player_team = 'dire'
                        print(f"[GSI] ✅ DIRE (справа)")

                # Статус игры
                map_data = data.get("map", {})
                game_state = map_data.get("game_state", "")

                # === СБРОС КОМАНДЫ ПРИ НОВОЙ ИГРЕ ===
                if self.last_game_state and "POST_GAME" in self.last_game_state:
                    if "HERO_SELECTION" in game_state or "STRATEGY_TIME" in game_state:
                        print(f"[GSI] 🔄 НОВАЯ ИГРА! Сбрасываем команду")
                        self.player_team = None
                        self.game_in_progress = False

                # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Сбрасываем команду если долго нет обновлений (30+ сек)
                # Это защита от "залипшей" команды из прошлой игры
                time_since_update = time.time() - self.last_update if self.last_update > 0 else 0
                if time_since_update > 30.0 and self.player_team:
                    print(f"[GSI] ⚠️ Нет обновлений {time_since_update:.1f} сек, сбрасываем команду")
                    self.player_team = None
                    self.game_in_progress = False

                self.last_game_state = game_state
                self.game_time = map_data.get("game_time", 0)

                if "HERO_SELECTION" in game_state or "GAME_IN_PROGRESS" in game_state:
                    if not self.game_in_progress:
                        self.game_in_progress = True
                        print(f"[GSI] 🎮 Игра началась!")

                elif "POST_GAME" in game_state or "DISCONNECT" in game_state:
                    if self.game_in_progress:
                        self.game_in_progress = False
                        self.player_team = None
                        print(f"[GSI] ⏹️ Игра завершена")

                return "OK", 200

            except Exception as e:
                print(f"[GSI] ❌ Ошибка: {e}")
                return "Error", 500

        @self.app.route('/team', methods=['GET'])
        def get_team():
            # Проверяем актуальность данных (если обновление было >30 сек назад - команда недействительна)
            time_since_update = time.time() - self.last_update if self.last_update > 0 else 999
            if time_since_update > 30.0:
                # Данные устарели - возвращаем None
                return jsonify({"team": None})
            return jsonify({"team": self.player_team or None})

        @self.app.route('/status', methods=['GET'])
        def get_status():
            return jsonify({
                "connected": self.last_update > 0,
                "team": self.player_team,
                "in_progress": self.game_in_progress,
                "game_time": self.game_time
            })

    def auto_setup_gsi(self):
        """Автопоиск Dota 2 и создание конфига"""
        print("[GSI] 🔍 Поиск Dota 2...")

        drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        paths = [
            "Program Files (x86)\\Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration",
            "SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration",
            "Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration",
        ]

        dota_path = None
        for drive in drives:
            for path in paths:
                full = os.path.join(drive, path)
                if os.path.exists(full):
                    dota_path = full
                    break
            if dota_path:
                break

        if not dota_path:
            print("[GSI] ⚠️ Папка gamestate_integration не найдена")
            print("[GSI] 🔨 Пытаюсь создать папку...")

            # Ищем папку Dota 2 (без gamestate_integration)
            dota_base = None
            for drive in drives:
                base_paths = [
                    "Program Files (x86)\\Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg",
                    "SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg",
                    "Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg",
                ]
                for base_path in base_paths:
                    full = os.path.join(drive, base_path)
                    if os.path.exists(full):
                        dota_base = full
                        break
                if dota_base:
                    break

            if dota_base:
                # Создаём папку gamestate_integration
                dota_path = os.path.join(dota_base, "gamestate_integration")
                try:
                    os.makedirs(dota_path, exist_ok=True)
                    print(f"[GSI] ✅ Папка создана: {dota_path}")
                except Exception as e:
                    print(f"[GSI] ❌ Не удалось создать папку: {e}")
                    print(f"[GSI] 📝 Создай папку вручную: {dota_path}")
                    return
            else:
                print("[GSI] ❌ Dota 2 не найдена!")
                print("[GSI] 📝 Укажи путь вручную в коде или установи Dota 2")
                return

        config_file = os.path.join(dota_path, "gamestate_integration_metamind.cfg")

        config_content = '''"MetaMind GSI"
{
    "uri"           "http://localhost:3000"
    "timeout"       "5.0"
    "buffer"        "0.1"
    "throttle"      "0.1"
    "heartbeat"     "30.0"
    "data"
    {
        "provider"      "1"
        "map"           "1"
        "player"        "1"
        "hero"          "1"
        "draft"         "1"
    }
}'''

        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            print(f"[GSI] ✅ Конфиг создан: {config_file}")
        except Exception as e:
            print(f"[GSI] ❌ Ошибка: {e}")

    def run(self):
        """Запуск сервера"""
        print("[GSI] 🌐 Сервер запущен на http://localhost:3000")
        try:
            self.app.run(host='0.0.0.0', port=3000, debug=False, use_reloader=False)
        except Exception as e:
            print(f"[GSI] ❌ Ошибка запуска: {e}")


def start_gsi_server():
    """Запуск GSI в отдельном потоке"""
    gsi = GSIServer()
    gsi.run()


# ================= КОНФИГУРАЦИЯ ПРИЛОЖЕНИЯ =================

APP_VERSION = "6.3"
CACHE_UPDATE_HOURS = 24
APP_DATA_FOLDER = "MetaMind"

SPLASH_IMAGE_FILE = "1.png"
WHATS_NEW_IMAGE_FILE = "largo_news.png"

DATA_FILE = "hero_data.json"
AM_COUNTERS_FILE = "antimage_counters.json"
OPENDOTA_CACHE_FILE = "opendota_cache.json"
OPENDOTA_CACHE_META_FILE = "opendota_cache_meta.json"
VERSION_FILE = "last_version.txt"

MAX_ENEMIES = 5
AM_SLUG = "anti-mage"

BACKGROUND_IMAGE_FILE = "background.jpg"

ICON_PATH = 'hero_icons/'
ICON_WIDTH_SMALL = 45
ICON_HEIGHT_SMALL = 25
ICON_WIDTH_LARGE = 60
ICON_HEIGHT_LARGE = 34
SCAN_THUMB_SIZE = (150, 75)
SIFT_TEMPLATE_SIZE = (100, 56)
FLOATING_ICON_SIZE = 34
FLOATING_ICON_IMAGE_SIZE = 26
UI_SCALE = 1.0

COLOR_DARK_BG = "transparent"
COLOR_ACCENT = "#dc2626"
COLOR_ACCENT_DARK = "#991b1b"
COLOR_PURPLE = "#9333ea"
COLOR_SUCCESS_GREEN = "#22c55e"
COLOR_DANGER_RED = "#dc2626"
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_GRAY = "#9ca3af"
BORDER_RADIUS = "12px"
COLOR_HOVER = "rgba(55, 65, 81, 0.8)"
COLOR_TRANSPARENT_CARD = "rgba(20, 20, 20, 0.8)"
COLOR_GLASS_DARK = "rgba(0, 0, 0, 0.5)"
COLOR_GLASS_MEDIUM = "rgba(15, 15, 15, 0.7)"
COLOR_GLASS_LIGHT = "rgba(30, 30, 30, 0.6)"

FONT_FAMILY_MAIN = "Arial, Helvetica, sans-serif"
FONT_FAMILY_LOGO = "Arial Black, Impact, sans-serif"

OPENDOTA_HEROSTATS = "https://api.opendota.com/api/heroStats"
OPENDOTA_HEROSTATS_ALT = "https://opendota.com/api/heroStats"
OPENDOTA_HEROSTATS_ALT2 = "https://www.opendota.com/api/heroStats"

# ================= СТАТИЧЕСКИЕ ДАННЫЕ (FALLBACK) =================
STATIC_HERO_META = None


def get_static_fallback():
    """Возвращает статические данные в формате OpenDota API"""
    global STATIC_HERO_META
    if STATIC_HERO_META:
        return STATIC_HERO_META

    STATIC_HERO_META = []

    # Carry
    carries = [
        ("anti_mage", "Anti-Mage", 50.8, 9870),
        ("phantom_assassin", "Phantom Assassin", 52.8, 15420),
        ("juggernaut", "Juggernaut", 52.3, 18650),
        ("slark", "Slark", 51.9, 12340),
        ("faceless_void", "Faceless Void", 51.1, 13450),
        ("spectre", "Spectre", 51.7, 9120),
        ("terrorblade", "Terrorblade", 49.2, 6780),
        ("morphling", "Morphling", 48.9, 5430),
        ("naga_siren", "Naga Siren", 49.5, 4890),
        ("medusa", "Medusa", 50.3, 7650),
        ("phantom_lancer", "Phantom Lancer", 50.1, 8340),
        ("luna", "Luna", 51.5, 8920),
        ("gyrocopter", "Gyrocopter", 50.7, 11230),
        ("lifestealer", "Lifestealer", 51.2, 9870),
        ("ursa", "Ursa", 52.1, 10450),
        ("troll_warlord", "Troll Warlord", 51.2, 7920),
        ("wraith_king", "Wraith King", 53.2, 11230),
        ("sven", "Sven", 51.8, 13450),
        ("chaos_knight", "Chaos Knight", 50.9, 8920),
        ("drow_ranger", "Drow Ranger", 50.9, 10340),
        ("weaver", "Weaver", 50.4, 9120),
        ("riki", "Riki", 51.3, 12340),
        ("bloodseeker", "Bloodseeker", 50.8, 11230),
        ("clinkz", "Clinkz", 51.7, 8920),
        ("monkey_king", "Monkey King", 50.2, 9870),
        ("muerta", "Muerta", 49.8, 7650),
        ("razor", "Razor", 50.5, 10340),
        ("kez", "Kez", 49.3, 5430),
    ]

    for slug, name, wr, picks in carries:
        wins = int(picks * wr / 100)
        STATIC_HERO_META.append({
            "id": len(STATIC_HERO_META) + 1,
            "name": f"npc_dota_hero_{slug}",
            "localized_name": name,
            "1_pick": picks // 8,
            "1_win": wins // 8,
            "2_pick": picks // 8,
            "2_win": wins // 8,
            "3_pick": picks // 8,
            "3_win": wins // 8,
            "4_pick": picks // 8,
            "4_win": wins // 8,
            "5_pick": picks // 8,
            "5_win": wins // 8,
            "6_pick": picks // 8,
            "6_win": wins // 8,
            "7_pick": picks // 8,
            "7_win": wins // 8,
            "8_pick": picks // 8,
            "8_win": wins // 8,
            "pro_pick": picks // 10,
            "pro_win": wins // 10,
        })

    # Mider
    miders = [
        ("shadow_fiend", "Shadow Fiend", 50.2, 18920),
        ("storm_spirit", "Storm Spirit", 50.7, 14320),
        ("invoker", "Invoker", 49.8, 22340),
        ("queen_of_pain", "Queen of Pain", 51.3, 16540),
        ("puck", "Puck", 50.9, 13210),
        ("templar_assassin", "Templar Assassin", 51.2, 10230),
        ("ember_spirit", "Ember Spirit", 50.1, 12450),
        ("outworld_destroyer", "Outworld Destroyer", 50.5, 9870),
        ("tinker", "Tinker", 48.7, 8540),
        ("leshrac", "Leshrac", 50.8, 9120),
        ("lina", "Lina", 51.8, 15670),
        ("zeus", "Zeus", 52.3, 19230),
        ("void_spirit", "Void Spirit", 49.4, 11890),
        ("kunkka", "Kunkka", 49.9, 10670),
        ("death_prophet", "Death Prophet", 52.1, 11340),
        ("necrophos", "Necrophos", 51.5, 12340),
        ("viper", "Viper", 51.9, 13450),
        ("huskar", "Huskar", 50.3, 8920),
        ("broodmother", "Broodmother", 49.7, 6780),
        ("arc_warden", "Arc Warden", 48.9, 5430),
        ("alchemist", "Alchemist", 50.1, 9870),
        ("sniper", "Sniper", 51.4, 14320),
        ("windranger", "Windranger", 50.6, 11230),
        ("batrider", "Batrider", 49.8, 7650),
        ("pangolier", "Pangolier", 50.2, 8920),
        ("dragon_knight", "Dragon Knight", 51.7, 11450),
        ("meepo", "Meepo", 48.3, 4560),
        ("visage", "Visage", 49.5, 5430),
        ("lone_druid", "Lone Druid", 48.7, 6780),
        ("largo", "Largo", 50.0, 7650),
    ]

    for slug, name, wr, picks in miders:
        wins = int(picks * wr / 100)
        STATIC_HERO_META.append({
            "id": len(STATIC_HERO_META) + 1,
            "name": f"npc_dota_hero_{slug}",
            "localized_name": name,
            "1_pick": picks // 8,
            "1_win": wins // 8,
            "2_pick": picks // 8,
            "2_win": wins // 8,
            "3_pick": picks // 8,
            "3_win": wins // 8,
            "4_pick": picks // 8,
            "4_win": wins // 8,
            "5_pick": picks // 8,
            "5_win": wins // 8,
            "6_pick": picks // 8,
            "6_win": wins // 8,
            "7_pick": picks // 8,
            "7_win": wins // 8,
            "8_pick": picks // 8,
            "8_win": wins // 8,
            "pro_pick": picks // 10,
            "pro_win": wins // 10,
        })

    # Offlaner
    offlaners = [
        ("axe", "Axe", 52.4, 17890),
        ("mars", "Mars", 51.8, 14320),
        ("tidehunter", "Tidehunter", 51.2, 12890),
        ("centaur_warrunner", "Centaur Warrunner", 53.1, 15670),
        ("bristleback", "Bristleback", 53.7, 16540),
        ("underlord", "Underlord", 51.5, 11230),
        ("doom", "Doom", 50.3, 10450),
        ("legion_commander", "Legion Commander", 52.1, 13670),
        ("slardar", "Slardar", 50.9, 9870),
        ("sand_king", "Sand King", 51.3, 12340),
        ("dark_seer", "Dark Seer", 50.2, 7650),
        ("batrider", "Batrider", 49.8, 8920),
        ("beastmaster", "Beastmaster", 50.5, 9120),
        ("brewmaster", "Brewmaster", 49.9, 7650),
        ("night_stalker", "Night Stalker", 51.3, 10890),
        ("primal_beast", "Primal Beast", 51.9, 12340),
        ("timbersaw", "Timbersaw", 49.5, 8920),
        ("pangolier", "Pangolier", 50.6, 9120),
        ("magnus", "Magnus", 50.8, 10340),
        ("spirit_breaker", "Spirit Breaker", 51.7, 11450),
        ("clockwerk", "Clockwerk", 50.4, 9870),
        ("omniknight", "Omniknight", 52.3, 10450),
        ("razor", "Razor", 50.5, 11230),
        ("enigma", "Enigma", 49.7, 8920),
        ("enchantress", "Enchantress", 50.1, 7650),
        ("phoenix", "Phoenix", 51.2, 9120),
        ("elder_titan", "Elder Titan", 49.8, 6780),
        ("pudge", "Pudge", 51.5, 13450),
        ("earthshaker", "Earthshaker", 50.9, 12340),
        ("shredder", "Shredder", 49.5, 8920),
    ]

    for slug, name, wr, picks in offlaners:
        wins = int(picks * wr / 100)
        STATIC_HERO_META.append({
            "id": len(STATIC_HERO_META) + 1,
            "name": f"npc_dota_hero_{slug}",
            "localized_name": name,
            "1_pick": picks // 8,
            "1_win": wins // 8,
            "2_pick": picks // 8,
            "2_win": wins // 8,
            "3_pick": picks // 8,
            "3_win": wins // 8,
            "4_pick": picks // 8,
            "4_win": wins // 8,
            "5_pick": picks // 8,
            "5_win": wins // 8,
            "6_pick": picks // 8,
            "6_win": wins // 8,
            "7_pick": picks // 8,
            "7_win": wins // 8,
            "8_pick": picks // 8,
            "8_win": wins // 8,
            "pro_pick": picks // 10,
            "pro_win": wins // 10,
        })

    # Support
    supports = [
        ("lion", "Lion", 50.3, 21340),
        ("rubick", "Rubick", 49.7, 16540),
        ("earth_spirit", "Earth Spirit", 48.9, 7650),
        ("mirana", "Mirana", 50.1, 14890),
        ("nyx_assassin", "Nyx Assassin", 50.7, 10340),
        ("phoenix", "Phoenix", 51.2, 9120),
        ("pugna", "Pugna", 50.5, 8920),
        ("skywrath_mage", "Skywrath Mage", 49.8, 10670),
        ("spirit_breaker", "Spirit Breaker", 51.7, 11450),
        ("tusk", "Tusk", 50.3, 9870),
        ("venomancer", "Venomancer", 51.4, 10340),
        ("windranger", "Windranger", 50.6, 11230),
        ("clockwerk", "Clockwerk", 50.4, 9870),
        ("earthshaker", "Earthshaker", 50.9, 12340),
        ("tiny", "Tiny", 51.4, 13210),
        ("elder_titan", "Elder Titan", 49.8, 6780),
        ("enigma", "Enigma", 49.7, 8920),
        ("furion", "Nature's Prophet", 50.2, 9870),
        ("sand_king", "Sand King", 51.3, 12340),
        ("pudge", "Pudge", 51.5, 13450),
        ("bounty_hunter", "Bounty Hunter", 50.8, 10340),
        ("techies", "Techies", 48.3, 5430),
        ("grimstroke", "Grimstroke", 51.7, 11450),
        ("dark_willow", "Dark Willow", 50.1, 8920),
        ("snapfire", "Snapfire", 51.8, 11890),
        ("hoodwink", "Hoodwink", 50.6, 9120),
        ("ringmaster", "Ringmaster", 49.9, 6780),
    ]

    for slug, name, wr, picks in supports:
        wins = int(picks * wr / 100)
        STATIC_HERO_META.append({
            "id": len(STATIC_HERO_META) + 1,
            "name": f"npc_dota_hero_{slug}",
            "localized_name": name,
            "1_pick": picks // 8,
            "1_win": wins // 8,
            "2_pick": picks // 8,
            "2_win": wins // 8,
            "3_pick": picks // 8,
            "3_win": wins // 8,
            "4_pick": picks // 8,
            "4_win": wins // 8,
            "5_pick": picks // 8,
            "5_win": wins // 8,
            "6_pick": picks // 8,
            "6_win": wins // 8,
            "7_pick": picks // 8,
            "7_win": wins // 8,
            "8_pick": picks // 8,
            "8_win": wins // 8,
            "pro_pick": picks // 10,
            "pro_win": wins // 10,
        })

    # Hard Support
    hard_supports = [
        ("crystal_maiden", "Crystal Maiden", 50.8, 19230),
        ("shadow_shaman", "Shadow Shaman", 52.1, 17650),
        ("witch_doctor", "Witch Doctor", 52.8, 18920),
        ("warlock", "Warlock", 53.2, 15670),
        ("dazzle", "Dazzle", 51.9, 13890),
        ("oracle", "Oracle", 49.2, 8920),
        ("chen", "Chen", 47.1, 3210),
        ("io", "Io", 48.3, 4560),
        ("undying", "Undying", 53.1, 13450),
        ("abaddon", "Abaddon", 51.7, 11230),
        ("winter_wyvern", "Winter Wyvern", 50.3, 10450),
        ("vengeful_spirit", "Vengeful Spirit", 51.2, 13890),
        ("ogre_magi", "Ogre Magi", 53.9, 20450),
        ("jakiro", "Jakiro", 51.6, 14320),
        ("disruptor", "Disruptor", 50.4, 11230),
        ("keeper_of_the_light", "Keeper of the Light", 50.1, 9870),
        ("shadow_demon", "Shadow Demon", 49.5, 7650),
        ("bane", "Bane", 50.7, 11230),
        ("lich", "Lich", 52.3, 14670),
        ("ancient_apparition", "Ancient Apparition", 51.4, 12340),
        ("enchantress", "Enchantress", 50.1, 7650),
        ("omniknight", "Omniknight", 52.3, 10450),
        ("treant_protector", "Treant Protector", 52.5, 8340),
        ("marci", "Marci", 51.2, 10230),
        ("snapfire", "Snapfire", 51.8, 11890),
        ("hoodwink", "Hoodwink", 50.6, 9120),
        ("silencer", "Silencer", 51.3, 12340),
    ]

    for slug, name, wr, picks in hard_supports:
        wins = int(picks * wr / 100)
        STATIC_HERO_META.append({
            "id": len(STATIC_HERO_META) + 1,
            "name": f"npc_dota_hero_{slug}",
            "localized_name": name,
            "1_pick": picks // 8,
            "1_win": wins // 8,
            "2_pick": picks // 8,
            "2_win": wins // 8,
            "3_pick": picks // 8,
            "3_win": wins // 8,
            "4_pick": picks // 8,
            "4_win": wins // 8,
            "5_pick": picks // 8,
            "5_win": wins // 8,
            "6_pick": picks // 8,
            "6_win": wins // 8,
            "7_pick": picks // 8,
            "7_win": wins // 8,
            "8_pick": picks // 8,
            "8_win": wins // 8,
            "pro_pick": picks // 10,
            "pro_win": wins // 10,
        })

    return STATIC_HERO_META


def calculate_ui_scale():
    """Определяет коэффициент масштаба по разрешению экрана."""
    app = QApplication.instance()
    if not app:
        return 1.0
    screen = app.primaryScreen()
    if not screen:
        return 1.0
    size = screen.size()
    base_width = 1920
    base_height = 1080
    scale = min(size.width() / base_width, size.height() / base_height)
    return max(0.75, min(1.5, scale))


def apply_ui_scale(scale):
    """Применяет масштаб к глобальным размерам UI/сканера."""
    global UI_SCALE
    global ICON_WIDTH_SMALL, ICON_HEIGHT_SMALL, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE
    global SCAN_THUMB_SIZE, SIFT_TEMPLATE_SIZE
    global FLOATING_ICON_SIZE, FLOATING_ICON_IMAGE_SIZE

    UI_SCALE = scale
    ICON_WIDTH_SMALL = max(24, int(round(45 * scale)))
    ICON_HEIGHT_SMALL = max(16, int(round(25 * scale)))
    ICON_WIDTH_LARGE = max(32, int(round(60 * scale)))
    ICON_HEIGHT_LARGE = max(20, int(round(34 * scale)))
    SCAN_THUMB_SIZE = (
        max(80, int(round(150 * scale))),
        max(40, int(round(75 * scale))),
    )
    SIFT_TEMPLATE_SIZE = (
        max(60, int(round(100 * scale))),
        max(34, int(round(56 * scale))),
    )
    FLOATING_ICON_SIZE = max(26, int(round(34 * scale)))
    FLOATING_ICON_IMAGE_SIZE = max(20, int(round(26 * scale)))


HERO_ROLES = {
    "Hard Support": [
        "crystal_maiden", "shadow_shaman", "witch_doctor", "warlock", "dazzle",
        "oracle", "chen", "io", "undying", "abaddon", "winter_wyvern",
        "vengeful_spirit", "ogre_magi", "jakiro", "disruptor", "keeper_of_the_light",
        "shadow_demon", "bane", "lich", "ancient_apparition", "enchantress",
        "omniknight", "treant_protector", "dark_willow", "grimstroke", "marci",
        "snapfire", "hoodwink", "silencer", "ringmaster"
    ],
    "Support": [
        "lion", "rubick", "earth_spirit", "mirana", "nyx_assassin",
        "phoenix", "pugna", "skywrath_mage", "spirit_breaker", "tusk",
        "venomancer", "windranger", "clockwerk", "earthshaker", "tiny",
        "elder_titan", "enigma", "furion", "sand_king", "pudge",
        "bounty_hunter", "techies",
        "grimstroke", "dark_willow", "snapfire", "hoodwink", "ringmaster", "largo"
    ],
    "Offlaner": [
        "axe", "mars", "tidehunter", "centaur_warrunner", "bristleback",
        "underlord", "doom", "legion_commander", "slardar", "sand_king",
        "dark_seer", "batrider", "beastmaster", "brewmaster", "dragon_knight",
        "night_stalker", "primal_beast", "timbersaw", "pangolier", "magnus",
        "spirit_breaker", "clockwerk", "omniknight", "death_prophet",
        "razor", "viper", "enigma", "enchantress",
        "phoenix", "elder_titan", "earthshaker", "kez", "largo", "shredder"
    ],
    "Mider": [
        "shadow_fiend", "storm_spirit", "invoker", "queen_of_pain", "puck",
        "templar_assassin", "ember_spirit", "outworld_destroyer", "tinker",
        "leshrac", "lina", "zeus", "void_spirit", "kunkka", "death_prophet",
        "necrophos", "viper", "huskar", "broodmother", "arc_warden",
        "alchemist", "bloodseeker", "sniper", "windranger", "batrider",
        "pangolier", "dragon_knight", "keeper_of_the_light", "tiny",
        "meepo", "visage", "lone_druid", "kez", "largo"
    ],
    "Carry": [
        "anti_mage", "phantom_assassin", "juggernaut", "slark", "faceless_void",
        "spectre", "terrorblade", "morphling", "naga_siren", "medusa",
        "phantom_lancer", "luna", "gyrocopter", "lifestealer", "ursa",
        "troll_warlord", "wraith_king", "sven", "chaos_knight", "drow_ranger",
        "weaver", "riki", "bloodseeker", "clinkz", "monkey_king",
        "muerta", "void_spirit", "ember_spirit", "alchemist",
        "templar_assassin", "razor", "kez"
    ]
}

ROLE_DISPLAY_NAMES = {
    "Hard Support": "Hard Support",
    "Support": "Support",
    "Offlaner": "Offlaner",
    "Mider": "Mider",
    "Carry": "Carry"
}

HERO_SLUG_MAP = {
    "antimage": "anti-mage",
    "anti_mage": "anti-mage",
    "queenofpain": "queen-of-pain",
    "queen_of_pain": "queen-of-pain",
    "nevermore": "shadow-fiend",
    "shadow_fiend": "shadow-fiend",
    "windrunner": "windranger",
    "windranger": "windranger",
    "skeleton_king": "wraith-king",
    "wraith_king": "wraith-king",
    "obsidian_destroyer": "outworld-destroyer",
    "outworld_destroyer": "outworld-destroyer",
    "outworld_devourer": "outworld-destroyer",
    "zuus": "zeus",
    "wisp": "io",
    "furion": "natures-prophet",
    "nature_s_prophet": "natures-prophet",
    "shredder": "timbersaw",
    "magnataur": "magnus",
    "rattletrap": "clockwerk",
    "necrolyte": "necrophos",
    "doom_bringer": "doom",
    "treant": "treant-protector",
    "treant_protector": "treant-protector",
    "centaur": "centaur-warrunner",
    "centaur_warrunner": "centaur-warrunner",
    "vengefulspirit": "vengeful-spirit",
    "vengeful_spirit": "vengeful-spirit",
    "life_stealer": "lifestealer",
    "lifestealer": "lifestealer",
    "abyssal_underlord": "underlord",
    "underlord": "underlord",
    "earthshaker": "earthshaker",
    "earth_shaker": "earthshaker",
    "doom": "doom",
    "io": "io",
    "zeus": "zeus",
    "timbersaw": "timbersaw",
    "magnus": "magnus",
    "clockwerk": "clockwerk",
    "necrophos": "necrophos",
    "primal_beast": "primal-beast",
    "marci": "marci",
    "muerta": "muerta",
    "dawnbreaker": "dawnbreaker",
    "void_spirit": "void-spirit",
    "snapfire": "snapfire",
    "hoodwink": "hoodwink",
    "ringmaster": "ringmaster",
    "kez": "kez",
    "largo": "largo",
}


# ================= УТИЛИТЫ =================

def resource_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path).replace(os.path.sep, '/')


def load_json_file(filename: str):
    full_path = resource_path(filename)
    if not os.path.exists(full_path):
        print(f"ОШИБКА: Файл базы данных не найден: {full_path}")
        return {}
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Ошибка чтения JSON из {full_path}: {e}")
        return {}


def get_app_data_path() -> str:
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA')
        if appdata:
            app_folder = os.path.join(appdata, APP_DATA_FOLDER)
        else:
            app_folder = os.path.join(os.path.expanduser('~'), APP_DATA_FOLDER)
    else:
        app_folder = os.path.join(os.path.expanduser('~'), '.' + APP_DATA_FOLDER.lower())

    if not os.path.exists(app_folder):
        try:
            os.makedirs(app_folder)
        except Exception as e:
            print(f"Не удалось создать папку {app_folder}: {e}")
            if getattr(sys, 'frozen', False):
                app_folder = os.path.dirname(sys.executable)
            else:
                app_folder = os.path.abspath(os.path.dirname(__file__))

    return app_folder


def get_bundled_cache_path() -> str:
    return resource_path(OPENDOTA_CACHE_FILE)


def get_cache_meta_path() -> str:
    return os.path.join(get_app_data_path(), OPENDOTA_CACHE_META_FILE)


def get_version_file_path() -> str:
    return os.path.join(get_app_data_path(), VERSION_FILE)


def get_last_shown_version() -> str | None:
    try:
        p = get_version_file_path()
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read().strip() or None
    except Exception as e:
        print(f"Ошибка чтения версии: {e}")
    return None


def save_current_version() -> bool:
    try:
        p = get_version_file_path()
        with open(p, 'w', encoding='utf-8') as f:
            f.write(APP_VERSION)
        return True
    except Exception as e:
        print(f"Ошибка сохранения версии: {e}")
        return False


def should_show_whats_new() -> bool:
    return get_last_shown_version() != APP_VERSION


def load_cache_meta() -> dict:
    try:
        p = get_cache_meta_path()
        if not os.path.exists(p):
            return {}
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception as e:
        print(f"Ошибка чтения meta кэша: {e}")
        return {}


def save_cache_meta(meta: dict) -> bool:
    try:
        p = get_cache_meta_path()
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Ошибка записи meta кэша: {e}")
        return False


def mark_cache(source: str, fetched_at: float | None = None, note: str = "") -> None:
    meta = {
        "source": source,  # net | bundled | appdata | static | unknown
        "fetched_at": float(fetched_at if fetched_at is not None else time.time()),
        "app_version": APP_VERSION,
        "note": note,
    }
    save_cache_meta(meta)


def _atomic_write_json(path: str, data) -> bool:
    try:
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"Ошибка атомарной записи JSON: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def save_json_file(filename: str, data) -> bool:
    try:
        full_path = os.path.join(get_app_data_path(), filename)
        ok = _atomic_write_json(full_path, data)
        if ok:
            print(f"Кэш сохранён в: {full_path}")
        return ok
    except Exception as e:
        print(f"Ошибка сохранения JSON в {filename}: {e}")
        return False


def load_opendota_cache(prefer_appdata: bool = True):
    if prefer_appdata:
        try:
            full_path = os.path.join(get_app_data_path(), OPENDOTA_CACHE_FILE)
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"Загружен кэш из AppData: {full_path} ({len(data)} героев)")
                    meta = load_cache_meta()
                    if not meta:
                        mark_cache("appdata", fetched_at=0, note="meta-missing")
                    return data
        except Exception as e:
            print(f"Ошибка загрузки кэша из AppData: {e}")

    try:
        bundled_path = get_bundled_cache_path()
        if os.path.exists(bundled_path):
            with open(bundled_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"📦 Загружен ВСТРОЕННЫЙ кэш (fallback): {bundled_path} ({len(data)} героев)")
                save_json_file(OPENDOTA_CACHE_FILE, data)
                mark_cache("bundled", fetched_at=0, note="bundled-cache-copied-to-appdata")
                return data
    except Exception as e:
        print(f"Ошибка загрузки встроенного кэша: {e}")

    return None


def is_cache_fresh() -> bool:
    try:
        meta = load_cache_meta()
        if not meta:
            return False
        if meta.get("source") not in ["net"]:
            return False
        # Безопасное преобразование в float
        try:
            fetched_at = float(meta.get("fetched_at", 0))
        except (ValueError, TypeError):
            return False
        if fetched_at <= 0:
            return False
        hours_old = (time.time() - fetched_at) / 3600
        print(f"Кэш обновлялся {hours_old:.1f} часов назад")
        return hours_old < CACHE_UPDATE_HOURS
    except Exception as e:
        print(f"Ошибка проверки свежести кэша: {e}")
        return False


def normalize_hero_name(name: str) -> str:
    return name.lower().replace('-', '').replace(' ', '')


def get_hero_icon_from_local(hero_slug: str, width: int, height: int):
    icon_file = resource_path(os.path.join(ICON_PATH, f'{hero_slug}.png'))
    if os.path.exists(icon_file):
        pixmap = QPixmap(icon_file)
        if not pixmap.isNull():
            return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


def load_pixmap_from_url(url: str, width: int, height: int):
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            buf = BytesIO(resp.content)
            pix = QPixmap()
            if pix.loadFromData(buf.getvalue()):
                return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return None
    return None


def _build_requests_session(total_retries: int) -> requests.Session:
    session = requests.Session()
    session.trust_env = True

    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504, 521, 522),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_opendota_hero_stats(status_cb=None, timeout=(4, 14), total_retries: int = 3):
    """Надёжная загрузка heroStats через OpenDota с fallback на статику."""

    headers = {
        'User-Agent': f'MetaMind/{APP_VERSION} (Dota 2 Counter Pick Helper)',
        'Accept': 'application/json'
    }

    urls = [OPENDOTA_HEROSTATS, OPENDOTA_HEROSTATS_ALT, OPENDOTA_HEROSTATS_ALT2]
    last_err: Exception | None = None

    session = _build_requests_session(total_retries=total_retries)

    for url in urls:
        try:
            if status_cb:
                status_cb(f"Подключение к OpenDota: {url}")

            try:
                resp = session.get(url, timeout=timeout, headers=headers, verify=certifi.where())
            except requests.exceptions.SSLError as ssl_err:
                last_err = ssl_err
                if status_cb:
                    status_cb("SSL проблема. Пробую альтернативный режим...")
                resp = session.get(url, timeout=timeout, headers=headers, verify=False)

            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 50:
                    print(f"OpenDota API: получено {len(data)} героев")
                    return data
            last_err = RuntimeError(f"HTTP {resp.status_code}")
        except Exception as e:
            last_err = e
            continue

    # Все API не работают - используем статику
    print(f"OpenDota API недоступен (последняя ошибка: {last_err})")
    print(f"Переход на статические данные")

    if status_cb:
        status_cb("API недоступен. Используются статические данные...")

    return get_static_fallback()


def refresh_opendota_cache_background() -> None:
    """Фоновое обновление кэша OpenDota. Не блокирует UI."""

    def worker():
        data = fetch_opendota_hero_stats(timeout=(4, 16), total_retries=3)
        if data:
            save_json_file(OPENDOTA_CACHE_FILE, data)
            if len(data) > 0 and "id" in data[0]:
                mark_cache("net")
            else:
                mark_cache("static", note="background-fallback")

    threading.Thread(target=worker, daemon=True).start()


# ================= UI: What's New =================
class WhatsNewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Что нового в MetaMind v{APP_VERSION}")
        self.setFixedSize(600, 450)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setWindowOpacity(0.0)

        self.container = QWidget(self)
        self.container.setGeometry(0, 0, 600, 450)

        image_path = resource_path(WHATS_NEW_IMAGE_FILE)
        if os.path.exists(image_path):
            bg_style = f"""
                QWidget#MainContainer {{
                    background-image: url({image_path});
                    background-repeat: no-repeat;
                    background-position: center;
                    border: 2px solid {COLOR_ACCENT};
                    border-radius: 16px;
                }}
            """
        else:
            bg_style = f"""
                QWidget#MainContainer {{
                    background-color: #0d0d0d;
                    border: 2px solid {COLOR_ACCENT};
                    border-radius: 16px;
                }}
            """

        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet(bg_style)

        overlay = QWidget(self.container)
        overlay.setGeometry(0, 0, 600, 450)
        overlay.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0.75);
            border-radius: 16px;
        """)

        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(25)

        title = QLabel(f"Что нового в v{APP_VERSION}")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLOR_TEXT_WHITE};
                font-size: 26px;
                font-weight: normal;
                font-family: {FONT_FAMILY_MAIN};
                background: transparent;
                border: none;
            }}
        """)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(10)

        changes_container = QWidget()
        changes_container.setStyleSheet("""
            QWidget {
                background-color: rgba(20, 20, 20, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)
        changes_layout = QVBoxLayout(changes_container)
        changes_layout.setContentsMargins(30, 25, 30, 25)
        changes_layout.setSpacing(14)

        changes = [
            ("", "Улучшено масштабирование UI под разные разрешения", COLOR_TEXT_WHITE),
            ("", "Окно теперь корректно меняет размер по границам", COLOR_TEXT_WHITE),
            ("", "Список подсказок героев показывает больше строк", COLOR_TEXT_WHITE),
        ]

        for icon, text, color in changes:
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent; border: none;")
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)

            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLOR_ACCENT};
                    font-size: 20px;
                    background: transparent;
                    border: none;
                }}
            """)
            icon_lbl.setFixedWidth(20)
            row.addWidget(icon_lbl)

            text_lbl = QLabel(text)
            text_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {color};
                    font-size: 15px;
                    background: transparent;
                    border: none;
                }}
            """)
            row.addWidget(text_lbl)
            row.addStretch()
            changes_layout.addWidget(row_widget)

        layout.addWidget(changes_container)
        layout.addStretch()

        close_btn = QPushButton("Понятно")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedHeight(50)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                border: none;
                border-radius: 10px;
                color: {COLOR_TEXT_WHITE};
                font-size: 16px;
                font-weight: bold;
                padding: 12px;
            }}
            QPushButton:hover {{
                background-color: #ef4444;
            }}
            QPushButton:pressed {{
                background-color: {COLOR_ACCENT_DARK};
            }}
        """)
        close_btn.clicked.connect(self._start_fade_out)
        layout.addWidget(close_btn)

        save_current_version()

        self.fade_in_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in_anim.setDuration(400)
        self.fade_in_anim.setStartValue(0.0)
        self.fade_in_anim.setEndValue(1.0)
        self.fade_in_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.fade_out_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out_anim.setDuration(300)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.setEasingCurve(QEasingCurve.InCubic)
        self.fade_out_anim.finished.connect(self.accept)

    def showEvent(self, event):
        super().showEvent(event)
        self.fade_in_anim.start()

    def _start_fade_out(self):
        self.fade_out_anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


# ================= UI: Splash =================
class SplashScreen(QWidget):
    def __init__(self, on_loaded_callback):
        super().__init__()

        # GSI кеш (оптимизация - нет лагов!)
        self._gsi_team_cache = None
        self._gsi_last_check = 0
        self._gsi_cache_duration = 3.0  # Кеш на 3 секунды
        self.on_loaded_callback = on_loaded_callback
        self.opendota_data = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setFixedSize(400, 400)

        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)

        icon_path = resource_path(SPLASH_IMAGE_FILE)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                if pixmap.width() > 300 or pixmap.height() > 300:
                    pixmap = pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_label.setPixmap(pixmap)
        else:
            self.icon_label.setText("MetaMind")
            self.icon_label.setStyleSheet(f"""
                color: {COLOR_ACCENT};
                font-size: 48px;
                font-weight: bold;
                font-family: {FONT_FAMILY_LOGO};
            """)

        layout.addWidget(self.icon_label)

        self.status_label = QLabel("Загрузка...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"""
            color: {COLOR_TEXT_WHITE};
            font-size: 14px;
            margin-top: 20px;
            background-color: transparent;
        """)
        layout.addWidget(self.status_label)

        self.setWindowOpacity(0.0)

        self.fade_in_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in_anim.setDuration(600)
        self.fade_in_anim.setStartValue(0.0)
        self.fade_in_anim.setEndValue(1.0)
        self.fade_in_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_in_anim.finished.connect(self._start_loading)

        self.fade_out_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out_anim.setDuration(500)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.setEasingCurve(QEasingCurve.InCubic)
        self.fade_out_anim.finished.connect(self._on_fade_out_finished)

    def start(self):
        self.show()
        self.fade_in_anim.start()

    def _start_loading(self):
        self.status_label.setText("Подготовка...")
        QApplication.processEvents()
        QTimer.singleShot(60, self._load_opendota_data)

    def _load_opendota_data(self):
        """Быстрый запуск из кэша; обновление — в фоне."""
        cached_data = load_opendota_cache(prefer_appdata=True)

        if cached_data:
            self.opendota_data = cached_data
            meta = load_cache_meta() or {}
            source = meta.get("source", "unknown")

            if is_cache_fresh():
                self.status_label.setText("Запуск...")
            else:
                if source == "bundled":
                    self.status_label.setText("Запуск... (загрузка свежих данных)")
                else:
                    self.status_label.setText("Запуск... (обновление в фоне)")
                refresh_opendota_cache_background()

            QApplication.processEvents()
            QTimer.singleShot(200, self._start_fade_out)
            return

        def set_status(t: str):
            self.status_label.setText(t)
            QApplication.processEvents()

        set_status("Загрузка данных OpenDota...")
        data = fetch_opendota_hero_stats(status_cb=set_status, timeout=(4, 16), total_retries=3)

        if data:
            self.opendota_data = data
            save_json_file(OPENDOTA_CACHE_FILE, data)
            if len(data) > 0 and "id" in data[0]:
                mark_cache("net")
                set_status("Готово!")
            else:
                mark_cache("static")
                set_status("Запуск (офлайн режим)...")
        else:
            set_status("Запуск без меты...")

        QTimer.singleShot(350, self._start_fade_out)

    def _start_fade_out(self):
        self.fade_out_anim.start()

    def _on_fade_out_finished(self):
        self.hide()
        self.on_loaded_callback(self.opendota_data)
        self.deleteLater()


# ================= UI: ResultRow =================
class ResultRow(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGraphicsEffect(None)
        self.setWindowOpacity(0.0)
        self.setMaximumHeight(0)

        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(500)
        self.opacity_anim.setStartValue(0.0)
        self.opacity_anim.setEndValue(1.0)
        self.opacity_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.height_anim = QPropertyAnimation(self, b"maximumHeight")
        self.height_anim.setDuration(500)
        self.height_anim.setStartValue(0)
        self.height_anim.setEasingCurve(QEasingCurve.OutCubic)

    def start_animation(self, height):
        self.height_anim.setEndValue(height)
        self.opacity_anim.start()
        self.height_anim.start()
        QTimer.singleShot(550, self._finish_animation)

    def _finish_animation(self):
        try:
            self.setMaximumHeight(16777215)
        except RuntimeError:
            pass


# ================= UI: RoleButton =================
class RoleButton(QPushButton):
    def __init__(self, role_key, display_name, parent=None):
        super().__init__(parent)
        self.role_key = role_key
        self.setText(display_name)
        self.setFixedHeight(52)
        self.setMinimumWidth(140)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.update_style(False)

    def update_style(self, selected):
        if selected:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLOR_ACCENT};
                    border: 1px solid {COLOR_ACCENT};
                    border-radius: 10px;
                    color: {COLOR_TEXT_WHITE};
                    font-size: 14px;
                    font-weight: bold;
                    padding: 14px 24px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(0, 0, 0, 0.5);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 10px;
                    color: {COLOR_TEXT_GRAY};
                    font-size: 14px;
                    font-weight: bold;
                    padding: 14px 24px;
                }}
                QPushButton:hover {{
                    background-color: rgba(220, 38, 38, 0.15);
                    border: 1px solid {COLOR_ACCENT};
                    color: {COLOR_TEXT_WHITE};
                }}
                QPushButton:pressed {{
                    background-color: {COLOR_ACCENT};
                    color: {COLOR_TEXT_WHITE};
                }}
            """)


# ================= UI: HeroSearchFrame =================
class HeroSearchFrame(QWidget):
    def __init__(self, all_heroes, on_select_callback, parent_app):
        super().__init__()
        self.all_heroes = all_heroes
        self.on_select_callback = on_select_callback
        self.parent_app = parent_app
        self.current_matches = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        lbl = QLabel("АНАЛИЗ И ПОДБОР")
        lbl.setObjectName("TitleLabel")
        layout.addWidget(lbl)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("ИМЯ ГЕРОЯ...")
        self.entry.textChanged.connect(self.on_key_release)
        self.entry.returnPressed.connect(self.on_enter_pressed)
        layout.addWidget(self.entry)

        info_button_layout = QHBoxLayout()
        info_button_layout.setContentsMargins(0, 5, 0, 0)

        self.status_label = QLabel(f"Выбрано врагов: [0/{MAX_ENEMIES}]")
        self.status_label.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 13px;")
        info_button_layout.addWidget(self.status_label)

        info_button_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        clear_btn = QPushButton("ОЧИСТИТЬ")
        clear_btn.setFixedWidth(120)
        clear_btn.clicked.connect(self.parent_app.clear_enemies)
        info_button_layout.addWidget(clear_btn)

        layout.addLayout(info_button_layout)

        self.suggestions_frame = QFrame()
        self.suggestions_frame.setObjectName("SuggestionsFrame")
        self.suggestions_frame.setStyleSheet(f"""
            QFrame#SuggestionsFrame {{
                border: 1px solid {COLOR_ACCENT};
                border-radius: 4px;
                background: transparent;
            }}
        """)
        suggestions_layout = QVBoxLayout(self.suggestions_frame)
        suggestions_layout.setContentsMargins(1, 1, 1, 1)
        suggestions_layout.setSpacing(0)
        self.suggestions_frame.setVisible(False)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setVisible(False)
        self.suggestions_list.setFixedHeight(150)
        self.suggestions_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.suggestions_list.setFocusPolicy(Qt.StrongFocus)
        self.suggestions_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.suggestions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.suggestions_list.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        self.suggestions_list.itemClicked.connect(self.select_hero_from_list)
        suggestions_layout.addWidget(self.suggestions_list)
        layout.addWidget(self.suggestions_frame)

        layout.addItem(QSpacerItem(20, 15, QSizePolicy.Minimum, QSizePolicy.Fixed))

    def on_key_release(self, query):
        query = query.lower()
        self.suggestions_list.clear()
        self.current_matches = []

        if not query:
            self.suggestions_list.setVisible(False)
            if hasattr(self, "suggestions_frame"):
                self.suggestions_frame.setVisible(False)
            return

        matches = []
        for hero_slug in self.all_heroes:
            clean_name = hero_slug.replace("-", " ")
            if query in clean_name or query in hero_slug:
                matches.append(hero_slug)

        matches.sort(key=lambda x: x.startswith(query), reverse=True)
        self.current_matches = matches[:10]

        if self.current_matches:
            for hero_slug in self.current_matches:
                display_name = hero_slug.replace("-", " ").title()
                item = QListWidgetItem(display_name)
                item.setData(Qt.UserRole, hero_slug)
                self.suggestions_list.addItem(item)
            self.suggestions_list.setVisible(True)
            if hasattr(self, "suggestions_frame"):
                self.suggestions_frame.setVisible(True)
        else:
            self.suggestions_list.setVisible(False)
            if hasattr(self, "suggestions_frame"):
                self.suggestions_frame.setVisible(False)

    def on_enter_pressed(self):
        if len(self.current_matches) == 1:
            hero_slug = self.current_matches[0]
            self.entry.clear()
            self.suggestions_list.setVisible(False)
            if hasattr(self, "suggestions_frame"):
                self.suggestions_frame.setVisible(False)
            self.current_matches = []
            self.on_select_callback(hero_slug)

    def select_hero_from_list(self, item):
        hero_slug = item.data(Qt.UserRole)
        self.entry.clear()
        self.suggestions_list.setVisible(False)
        if hasattr(self, "suggestions_frame"):
            self.suggestions_frame.setVisible(False)
        self.current_matches = []
        self.on_select_callback(hero_slug)

    def update_status(self, count):
        self.status_label.setText(f"Выбрано врагов: [{count}/{MAX_ENEMIES}]")


# ================= UI: FloatingIcon =================
class FloatingIcon(QWidget):
    """Прозрачная плавающая "M" в правом верхнем углу.

    Клик: toggle show/hide главного окна.
    Drag: перемещение.
    """

    def __init__(self, main_window_ref):
        super().__init__()
        self.main_window_ref = main_window_ref
        self._drag_pos = None
        self._moved = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(FLOATING_ICON_SIZE, FLOATING_ICON_SIZE)

        screen = QApplication.primaryScreen().geometry()
        x = screen.width() - self.width() - int(18 * UI_SCALE)
        y = int(18 * UI_SCALE)
        self.move(x, y)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setCursor(Qt.PointingHandCursor)

        icon_path = resource_path(SPLASH_IMAGE_FILE)
        pixmap = None
        if os.path.exists(icon_path):
            p = QPixmap(icon_path)
            if not p.isNull():
                pixmap = p.scaled(
                    FLOATING_ICON_IMAGE_SIZE,
                    FLOATING_ICON_IMAGE_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )

        if pixmap:
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setStyleSheet("background: transparent; border: none;")
        else:
            self.icon_label.setText("M")
            self.icon_label.setStyleSheet(f"""
                QLabel {{
                    background: transparent;
                    border: none;
                    color: {COLOR_TEXT_WHITE};
                    font-family: {FONT_FAMILY_LOGO};
                    font-size: 22px;
                }}
            """)

        layout.addWidget(self.icon_label)

        self.setWindowOpacity(0.55)

    def enterEvent(self, event):
        self.setWindowOpacity(0.95)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setWindowOpacity(0.55)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._moved = True
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._moved:
                self._toggle_main_window()
            self._drag_pos = None
            event.accept()

    def _toggle_main_window(self):
        if not self.main_window_ref:
            return
        if self.main_window_ref.isVisible():
            self.main_window_ref.hide()
        else:
            self.main_window_ref.show()
            self.main_window_ref.activateWindow()
            self.main_window_ref.raise_()


# ================= Signals =================
class _CacheSignals(QObject):
    done = Signal(bool, object, str)


# ================= MainWindow =================

# ================= CV SCANNER =================


class CVScannerSignals(QObject):
    """Сигналы для обновления UI"""
    progress = Signal(str)
    heroes_found = Signal(list, str)
    error = Signal(str)
    scanning_finished = Signal()


# ================= SMART PICK DETECTOR =================
import hashlib


class PickDetectorSignals(QObject):
    """Сигналы детектора пиков"""
    pick_detected = Signal()
    status = Signal(str)


class PickDetector:
    """Умный детектор пиков - следит за изменением фона портретов"""

    def __init__(self):
        self.signals = PickDetectorSignals()
        self.monitoring = False
        self.player_team = None
        self.monitor_region = None
        self.last_hash = None
        self.pick_cooldown = 0
        self.last_screenshot = None
        self.start_time = None  # Время старта мониторинга (для задержки)

    def set_team(self, team):
        """Устанавливает команду и область мониторинга"""
        self.player_team = team

        screen = ImageGrab.grab()
        w, h = screen.size

        # ТОЛЬКО область портретов героев (точная зона!)
        top_margin = int(h * 0.08)  # Пропускаем верхние 8% (таймер)
        hero_area_height = int(h * 0.15)  # Только 15% высоты (портреты)  # Только 20% высоты (портреты)

        if team == "radiant":
            # Radiant (слева) → ПРАВАЯ половина (враги Dire)
            x1 = int(w * 0.55)  # Начинаем с 55% (пропускаем центр)
            y1 = top_margin
            x2 = int(w * 0.95)  # До 95% (пропускаем край)
            y2 = top_margin + hero_area_height
            print(f"[PICK] 📍 Radiant → мониторинг ПРАВОЙ области (Dire)")
        elif team == "dire":
            # Dire (справа) → ЛЕВАЯ половина (враги Radiant)
            x1 = int(w * 0.05)  # От 5%
            y1 = top_margin
            x2 = int(w * 0.45)  # До 45% (пропускаем центр)
            y2 = top_margin + hero_area_height
            print(f"[PICK] 📍 Dire → мониторинг ЛЕВОЙ области (Radiant)")
        else:
            x1 = int(w * 0.1)
            y1 = top_margin
            x2 = int(w * 0.9)
            y2 = top_margin + hero_area_height
            print(f"[PICK] 📍 Мониторинг области портретов")

        self.monitor_region = (x1, y1, x2, y2)
        print(f"[PICK] ✅ Область: x={x1}-{x2}, y={y1}-{y2}")
        print(f"[PICK] 📏 Размер: {x2 - x1}x{y2 - y1}px")

    def calculate_difference(self, img1, img2):
        """Вычисляет процент различия между двумя изображениями"""
        import numpy as np

        arr1 = np.array(img1)
        arr2 = np.array(img2)

        # Вычисляем разницу
        diff = np.abs(arr1.astype(int) - arr2.astype(int))

        # Считаем сколько пикселей изменилось значительно (>30 по яркости)
        changed_pixels = np.sum(diff > 30)
        total_pixels = arr1.size

        change_percent = (changed_pixels / total_pixels) * 100
        return change_percent

    def check_for_change(self):
        """УЛУЧШЕННАЯ проверка изменений с защитой от ложных срабатываний"""
        if not self.monitoring:
            return False

        # ЗАДЕРЖКА ПОСЛЕ СТАРТА: игнорируем изменения первые 7 секунд
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed < 7.0:
                return False
            # После истечения задержки обновляем статус один раз
            elif not hasattr(self, '_delay_passed'):
                self._delay_passed = True
                self.signals.status.emit("Ожидание пиков...")
                print(f"[PICK] ✅ Стабилизация завершена, начинаю детектирование")

        # Cooldown после предыдущего детекта (1.5 сек)
        if self.pick_cooldown > 0:
            self.pick_cooldown -= 1
            return False

        if not self.monitor_region:
            return False

        try:
            # Захватываем область портретов героев
            screenshot = ImageGrab.grab(bbox=self.monitor_region)
            screenshot = screenshot.resize(SCAN_THUMB_SIZE, Image.Resampling.LANCZOS)
            screenshot_gray = screenshot.convert('L')

            # ПЕРВЫЙ запуск - сохраняем базу (состояние до пиков)
            if self.last_screenshot is None:
                self.last_screenshot = screenshot_gray
                print(f"[PICK]  Базовое состояние сохранено")
                return False

            # Вычисляем процент изменений
            change_percent = self.calculate_difference(screenshot_gray, self.last_screenshot)

            # ПОВЫШЕННЫЙ ПОРОГ: 25% (чтобы не срабатывать при загрузке)
            # Пик героя обычно вызывает изменение 25-50%
            if change_percent < 25:
                return False

            # Фильтр слишком больших изменений (>90% = смена экрана/баг)
            if change_percent > 90:
                print(f"[PICK] ⚠️ Слишком большие изменения ({change_percent:.1f}%), обновляем базу")
                self.last_screenshot = screenshot_gray
                return False

            print(f"[PICK] 🎯 ПИК ОБНАРУЖЕН! Изменение: {change_percent:.1f}%")

            # ВАЖНО: Обновляем базу СРАЗУ после детекции
            self.last_screenshot = screenshot_gray

            # Cooldown: 5 тиков (1.5 сек при 300ms)
            self.pick_cooldown = 5

            # Эмитим сигнал - запустит сканирование
            self.signals.pick_detected.emit()
            return True

        except Exception as e:
            print(f"[PICK] ❌ Ошибка: {e}")
            return False

    def start_monitoring(self):
        """Запускает мониторинг с задержкой для стабилизации"""
        self.monitoring = True
        self.last_screenshot = None
        self.pick_cooldown = 0
        self.start_time = time.time()  # Запоминаем время старта
        self._delay_passed = False  # Флаг для обновления статуса
        print(f"[PICK] 👁️ Мониторинг запущен (порог: 25%, задержка: 7 сек)")
        self.signals.status.emit("Ожидание пиков")

    def stop_monitoring(self):
        """Останавливает мониторинг"""
        self.monitoring = False
        self.last_screenshot = None
        self.start_time = None
        self._delay_passed = False
        print(f"[PICK] ⏹️ Мониторинг остановлен")
        self.signals.status.emit("Мониторинг выключен")


class CVScanner:
    """Computer Vision сканер для определения героев"""

    def __init__(self, api_keys):
        self.signals = CVScannerSignals()
        self.is_scanning = False
        self.auto_scan_enabled = False
        self.player_team = None  # radiant или dire из GSI

        # Кеш проверки наличия героев на экране
        self._heroes_check_cache = None
        self._heroes_check_time = 0

        # Загружаем список героев из папки portraits
        self.available_heroes = self._load_heroes_from_portraits()
        print(f"[CV] Загружено {len(self.available_heroes)} героев из /portraits")

        # ОПТИМИЗАЦИЯ: Предзагрузка дескрипторов (ОДИН РАЗ!)
        self.hero_descriptors = {}
        self._preload_hero_descriptors()

        # Fallback на стандартный список если папка пустая
        if not self.available_heroes:
            print("[CV] Папка portraits пуста, используем стандартный список")
            self.available_heroes = [
                "anti-mage", "axe", "bane", "bloodseeker", "crystal-maiden",
                "drow-ranger", "earthshaker", "juggernaut", "mirana", "morphling",
                "shadow-fiend", "phantom-lancer", "puck", "pudge", "razor",
                "sand-king", "storm-spirit", "sven", "tiny", "vengeful-spirit",
                "windranger", "zeus", "kunkka", "lina", "lion",
                "shadow-shaman", "slardar", "tidehunter", "witch-doctor", "lich",
                "riki", "enigma", "tinker", "sniper", "necrophos",
                "warlock", "beastmaster", "queen-of-pain", "venomancer", "faceless-void",
                "wraith-king", "death-prophet", "phantom-assassin", "pugna", "templar-assassin",
                "viper", "luna", "dragon-knight", "dazzle", "clockwerk",
                "leshrac", "natures-prophet", "lifestealer", "dark-seer", "clinkz",
                "omniknight", "enchantress", "huskar", "night-stalker", "broodmother",
                "bounty-hunter", "weaver", "jakiro", "batrider", "chen",
                "spectre", "ancient-apparition", "doom", "ursa", "spirit-breaker",
                "gyrocopter", "alchemist", "invoker", "silencer", "outworld-destroyer",
                "lycan", "brewmaster", "shadow-demon", "lone-druid", "chaos-knight",
                "meepo", "treant-protector", "ogre-magi", "undying", "rubick",
                "disruptor", "nyx-assassin", "naga-siren", "keeper-of-the-light", "io",
                "visage", "slark", "medusa", "troll-warlord", "centaur-warrunner",
                "magnus", "timbersaw", "bristleback", "tusk", "skywrath-mage",
                "abaddon", "elder-titan", "legion-commander", "techies", "ember-spirit",
                "earth-spirit", "underlord", "terrorblade", "phoenix", "oracle",
                "winter-wyvern", "arc-warden", "monkey-king", "dark-willow", "pangolier",
                "grimstroke", "hoodwink", "void-spirit", "snapfire", "mars",
                "dawnbreaker", "marci", "primal-beast", "muerta", "ringmaster",
                "kez", "largo"
            ]

    def _load_heroes_from_portraits(self):
        heroes = []
        portraits_dir = resource_path("portraits")

        if not os.path.exists(portraits_dir):
            print(f"[CV] Папка {portraits_dir} не найдена!")
            return heroes

        try:
            for filename in os.listdir(portraits_dir):
                if filename.endswith('.png'):
                    # Убираем .png и получаем slug героя
                    hero_slug = filename.replace('.png', '')
                    heroes.append(hero_slug)

            heroes.sort()
            return heroes

        except Exception as e:
            print(f"[CV] Ошибка загрузки героев: {e}")
            return heroes

    def _validate_hero(self, hero_slug):
        """Проверяет существует ли герой в папке portraits"""
        # Нормализуем имя
        normalized = hero_slug.lower().strip()

        # Проверяем точное совпадение
        if normalized in self.available_heroes:
            return True

        # Проверяем вариации (с подчеркиванием вместо дефиса)
        alternative = normalized.replace('-', '_')
        if alternative in self.available_heroes:
            return True

        alternative2 = normalized.replace('_', '-')
        if alternative2 in self.available_heroes:
            return True

        # Проверяем без разделителей
        no_sep = normalized.replace('-', '').replace('_', '')
        for hero in self.available_heroes:
            if hero.replace('-', '').replace('_', '') == no_sep:
                return True

        return False

    def capture_screen(self):
        return ImageGrab.grab()

    def image_to_base64(self, image):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    def _preload_hero_descriptors(self):
        """ОПТИМИЗАЦИЯ: Предзагружает SIFT дескрипторы всех героев"""
        portraits_dir = resource_path("portraits")

        if not os.path.exists(portraits_dir):
            print(f"[CV] ⚠️ Папка portraits не найдена, пропускаем предзагрузку")
            return

        print(f"[CV] 🚀 Предзагрузка SIFT дескрипторов...")
        start_time = time.time()

        sift = cv2.SIFT_create()
        png_files = [f for f in os.listdir(portraits_dir) if f.endswith('.png')]

        loaded_count = 0
        for filename in png_files:
            hero_slug = filename.replace('.png', '')
            template_path = os.path.join(portraits_dir, filename)

            try:
                # Загружаем портрет
                template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
                if template is None:
                    continue

                # ОПТИМИЗАЦИЯ: Уменьшаем разрешение (быстрее без потери точности)
                template_small = cv2.resize(template, SIFT_TEMPLATE_SIZE, interpolation=cv2.INTER_AREA)

                # Вычисляем SIFT дескрипторы
                kp, des = sift.detectAndCompute(template_small, None)

                if des is not None and len(kp) >= 2:
                    self.hero_descriptors[hero_slug] = (kp, des)
                    loaded_count += 1

            except Exception as e:
                continue

        elapsed = time.time() - start_time
        print(f"[CV] ✅ Предзагружено {loaded_count} героев за {elapsed:.2f} сек")

    def detect_heroes_with_sift(self, screenshot):
        """SIFT - СКАНИРОВАНИЕ ТОЛЬКО ВЕРХА ЭКРАНА"""

        self.signals.progress.emit("Анализ верхней части...")
        print(f"[SIFT] Начинаем SIFT сканирование...")

        screenshot_np = np.array(screenshot)
        screenshot_gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)

        h, w = screenshot_gray.shape

        # === ТОЛЬКО ВЕРХНЯЯ ЧАСТЬ (портреты в драфте) ===
        top_portion = int(h * 0.25)  # Верхние 25% экрана
        screenshot_gray = screenshot_gray[:top_portion, :]

        print(f"[SIFT] Сканируем верх: {w}x{top_portion}px")

        # Зона поиска (левая или правая половина)
        if self.player_team == "radiant":
            search_zone = screenshot_gray[:, w // 2:]
            offset_x = w // 2
            print(f"[SIFT] Radiant → сканируем ПРАВУЮ половину (враги Dire)")
        elif self.player_team == "dire":
            search_zone = screenshot_gray[:, :w // 2]
            offset_x = 0
            print(f"[SIFT] Dire → сканируем ЛЕВУЮ половину (враги Radiant)")
        else:
            search_zone = screenshot_gray
            offset_x = 0
            print(f"[SIFT] ⚠️ Команда не установлена, сканируем весь верх")

        # SIFT
        sift = cv2.SIFT_create()
        kp_screen, des_screen = sift.detectAndCompute(search_zone, None)

        if des_screen is None:
            return {"success": False, "error": "Нет features"}

        # FLANN matcher
        # ОПТИМИЗАЦИЯ: FLANN параметры (trees: 5→3 = быстрее)
        FLANN_INDEX_KDTREE = 1
        index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=3)
        search_params = dict(checks=50)
        flann = cv2.FlannBasedMatcher(index_params, search_params)

        # ОПТИМИЗАЦИЯ: Используем предзагруженные дескрипторы!
        if not self.hero_descriptors:
            print(f"[SIFT] ⚠️ Дескрипторы не загружены, используем медленный режим")
            # Fallback на старый метод (если кеш пустой)
            portraits_dir = resource_path("portraits")
            if not os.path.exists(portraits_dir):
                return {"success": False, "error": "Папка portraits не найдена"}
            png_files = [f for f in os.listdir(portraits_dir) if f.endswith('.png')]
            if len(png_files) == 0:
                return {"success": False, "error": "Нет PNG файлов"}

        matches_data = []
        checked_count = 0

        # ОПТИМИЗАЦИЯ: Используем готовые дескрипторы вместо загрузки!
        for hero_slug, (kp_template, des_template) in self.hero_descriptors.items():
            checked_count += 1

            try:
                if des_template is None or len(kp_template) < 2:
                    continue

                matches = flann.knnMatch(des_template, des_screen, k=2)

                good_matches = []
                for m_n in matches:
                    if len(m_n) == 2:
                        m, n = m_n
                        if m.distance < 0.7 * n.distance:
                            good_matches.append(m)

                if len(good_matches) > 6:
                    src_pts = np.float32([kp_template[m.queryIdx].pt for m in good_matches])
                    dst_pts = np.float32([kp_screen[m.trainIdx].pt for m in good_matches])

                    avg_x = int(np.mean(dst_pts[:, 0])) + offset_x
                    avg_y = int(np.mean(dst_pts[:, 1]))

                    confidence = len(good_matches) / max(len(kp_template), 1)

                    # Детальное логирование
                    print(
                        f"[SIFT] 🎯 {hero_slug}: {len(good_matches)} matches (kp:{len(kp_template)}, conf:{confidence:.2f})")

                    matches_data.append({
                        "hero": hero_slug,
                        "good_matches": len(good_matches),
                        "confidence": min(confidence, 1.0),
                        "position": (avg_x, avg_y)
                    })

            except:
                continue

        if len(matches_data) == 0:
            print(f"[SIFT] Не найдено совпадений после проверки {len(png_files)} героев")
            return {"success": False, "error": "Нет совпадений"}

        print(f"[SIFT]  Найдено {len(matches_data)} кандидатов, фильтруем...")

        matches_data.sort(key=lambda x: x['good_matches'], reverse=True)

        # Убираем дубликаты по позиции
        unique_matches = []
        for match in matches_data:
            is_dup = False
            for existing in unique_matches:
                dx = abs(match['position'][0] - existing['position'][0])
                dy = abs(match['position'][1] - existing['position'][1])
                if (dx ** 2 + dy ** 2) ** 0.5 < 100:
                    is_dup = True
                    break
            if not is_dup:
                unique_matches.append(match)
                # ОПТИМИЗАЦИЯ: Ранний выход при 5 героях
                if len(unique_matches) >= 5:
                    print(
                        f"[SIFT] ⚡ Найдено 5 героев, прекращаем поиск (проверено {checked_count}/{len(self.hero_descriptors)})")
                    break

        enemies = [m['hero'] for m in unique_matches]

        print(
            f"[SIFT]  Найдено {len(enemies)} героев (проверено {checked_count}/{len(self.hero_descriptors)}): {enemies}")

        return {
            "enemies": enemies,
            "confidence": "high" if len(enemies) == 5 else "medium",
            "success": True
        }

    def detect_heroes_with_opencv(self, screenshot):
        return self.detect_heroes_with_sift(screenshot)

    def detect_heroes_with_ai(self, screenshot):
        return self.detect_heroes_with_sift(screenshot)

    def check_heroes_on_screen(self, force_check=False):
        """Быстрая проверка наличия героев на экране (для запуска детектора пиков)"""
        # Кеширование результата на 0.5 секунды (быстрее реакция на начало игры)
        current_time = time.time()
        if not force_check and hasattr(self, '_heroes_check_cache') and hasattr(self, '_heroes_check_time'):
            if current_time - self._heroes_check_time < 0.5:
                return self._heroes_check_cache

        try:
            screenshot = self.capture_screen()
            result = self.detect_heroes_with_sift(screenshot)

            if result.get("success"):
                heroes = result.get("enemies", [])
                # Если найдено хотя бы 1-2 героя - значит игра началась
                has_heroes = len(heroes) >= 1
                if has_heroes:
                    print(f"[CHECK] ✅ Герои на экране: {len(heroes)} (можно начинать детекцию)")
                else:
                    print(f"[CHECK] ❌ Героев на экране не найдено (игра еще не началась)")

                # Кешируем результат
                self._heroes_check_cache = has_heroes
                self._heroes_check_time = current_time
                return has_heroes

            # Не найдено героев
            self._heroes_check_cache = False
            self._heroes_check_time = current_time
            print(f"[CHECK] ❌ Героев на экране не найдено (игра еще не началась)")
            return False
        except Exception as e:
            print(f"[CHECK] ⚠️ Ошибка проверки героев: {e}")
            self._heroes_check_cache = False
            self._heroes_check_time = current_time
            return False

    def scan_once(self, delay=2):
        """Одиночное сканирование"""
        if self.is_scanning:
            self.signals.progress.emit("Уже идёт сканирование...")
            print("[SCAN] ⚠️ is_scanning=True, пропускаем")
            return

        def worker():
            print("[SCAN] 🟢 START: is_scanning=False → True")
            self.is_scanning = True

            try:
                if delay > 0:
                    for i in range(delay, 0, -1):
                        self.signals.progress.emit(f"Сканирование через {i}...")
                        time.sleep(1)

                self.signals.progress.emit("Делаю скриншот...")
                screenshot = self.capture_screen()

                result = self.detect_heroes_with_ai(screenshot)

                if result.get("success"):
                    enemies = result.get("enemies", [])
                    confidence = result.get("confidence", "unknown")
                    self.signals.heroes_found.emit(enemies, confidence)
                else:
                    self.signals.error.emit(f"Ошибка: {result.get('error', 'Unknown')}")

            except Exception as e:
                print(f"[SCAN] ❌ EXCEPTION: {e}")
                self.signals.error.emit(f"Ошибка: {e}")

            finally:
                print("[SCAN] 🔴 END: is_scanning=True → False")
                self.is_scanning = False
                self.signals.scanning_finished.emit()

        threading.Thread(target=worker, daemon=True).start()


class TeamSelectionDialog(QDialog):
    """Диалог выбора команды"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбери команду")
        self.setModal(True)
        self.setFixedSize(400, 200)
        self.selected_team = None

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        title = QLabel("В какой команде ты играешь?")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white;")
        layout.addWidget(title)

        buttons = QHBoxLayout()
        buttons.setSpacing(15)

        radiant_btn = QPushButton("СВЕТ (Radiant)\nЯ слева")
        radiant_btn.setFixedHeight(80)
        radiant_btn.setStyleSheet("""
            QPushButton {
                background-color: #22c55e;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        radiant_btn.clicked.connect(lambda: self.select_team("radiant"))
        buttons.addWidget(radiant_btn)

        dire_btn = QPushButton("ТЬМА (Dire)\nЯ справа")
        dire_btn.setFixedHeight(80)
        dire_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #991b1b; }
        """)
        dire_btn.clicked.connect(lambda: self.select_team("dire"))
        buttons.addWidget(dire_btn)

        layout.addLayout(buttons)
        self.setStyleSheet("QDialog { background-color: #1f2937; }")

    def select_team(self, team):
        self.selected_team = team
        self.accept()


class MainWindow(QMainWindow):
    old_pos: QPoint | None = None
    _resizing = False
    _resize_edges: tuple[bool, bool, bool, bool] | None = None
    _resize_start_pos: QPoint | None = None
    _resize_start_geom: QRect | None = None
    _resize_margin = 8

    def _toggle_auto_scan_button(self):
        """Переключатель автосканирования (кнопка)"""
        is_enabled = self.auto_scan_btn.isChecked()

        if is_enabled:
            self.auto_scan_btn.setText("Автосканирование: ВКЛ")
        else:
            self.auto_scan_btn.setText("Автосканирование: ВЫКЛ")

        self.toggle_auto_scan(is_enabled)

    def play_success_sound(self):
        """Проигрывает приятный звук при нахождении контрпиков"""
        try:
            # Используем системный звук Windows
            winsound.MessageBeep(winsound.MB_OK)
        except:
            pass

    def get_player_team_from_gsi(self):
        """ИДЕАЛЬНОЕ определение команды через GSI с ретраями"""
        for attempt in range(3):  # 3 попытки
            try:
                response = requests.get('http://localhost:3000/player', timeout=0.5)
                if response.status_code == 200:
                    data = response.json()
                    team = data.get('team', '').lower()

                    if 'radiant' in team:
                        print(f"[GSI] RADIANT")
                        return 'radiant'
                    elif 'dire' in team:
                        print(f"[GSI] DIRE")
                        return 'dire'
                    else:
                        print(f"[GSI]  Команда не определена: {team}")

            except requests.exceptions.Timeout:
                if attempt < 2:
                    continue  # Ретрай
            except requests.exceptions.ConnectionError:
                print("[GSI] ❌ Сервер недоступен ( gsi_server.py)")
                break
            except Exception as e:
                print(f"[GSI] ❌ {e}")
                break

        return None

    def __init__(self):
        super().__init__()

        apply_ui_scale(calculate_ui_scale())

        self._signals = _CacheSignals()
        self._signals.done.connect(self._on_cache_refresh_done)
        self._refresh_in_progress = False

        self.setWindowTitle("MetaMind")
        self.setGeometry(100, 100, 1200, 850)
        self.setMinimumSize(800, 600)
        self.setWindowFlags(Qt.FramelessWindowHint)

        self.setWindowOpacity(0.0)
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.hero_data, self.am_counters_data = self.load_data()
        self.all_heroes = sorted(list(self.hero_data.keys()))
        self.selected_enemies = []
        self.selected_role = None

        self.opendota_cache = None

        self.animated_results = []
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._animate_next_result_row)
        self.animation_timer.setInterval(60)

        self.picker_animated_results = []
        self.picker_animation_timer = QTimer(self)
        self.picker_animation_timer.timeout.connect(self._animate_next_picker_row)
        self.picker_animation_timer.setInterval(90)

        self.setStyleSheet(self._generate_stylesheet())

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # === Header ===
        self.header = QFrame()
        self.header.setObjectName("HeaderFrame")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(30, 0, 30, 0)

        self.header.mousePressEvent = self.mousePressEvent
        self.header.mouseMoveEvent = self.mouseMoveEvent

        logo_container = QFrame()
        logo_layout = QHBoxLayout(logo_container)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(12)

        self.hamburger_button = QPushButton("≡")
        self.hamburger_button.setObjectName("HamburgerButton")
        self.hamburger_button.setFixedSize(40, 40)
        self.hamburger_button.setCursor(Qt.PointingHandCursor)
        self.hamburger_button.clicked.connect(self.toggle_sidebar)
        logo_layout.addWidget(self.hamburger_button)

        self.logo_icon = QLabel()
        logo_pixmap = None
        try:
            pixmap = QPixmap(resource_path("app_icon.png"))
            if not pixmap.isNull():
                logo_pixmap = pixmap.scaled(35, 35, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception as e:
            print(f"Ошибка загрузки app_icon.png: {e}")

        if logo_pixmap:
            self.logo_icon.setPixmap(logo_pixmap)
            self.logo_icon.setFixedSize(QSize(35, 35))
        else:
            self.logo_icon.setText("🎅")
            self.logo_icon.setStyleSheet(f"font-size: 30px; color: {COLOR_ACCENT}; font-weight: bold;")
            self.logo_icon.setFixedSize(QSize(35, 35))

        logo_layout.addWidget(self.logo_icon)

        self.logo_label = QLabel("MetaMind")
        self.logo_label.setObjectName("LogoText")
        logo_layout.addWidget(self.logo_label)

        header_layout.addWidget(logo_container, alignment=Qt.AlignLeft)
        header_layout.addStretch(1)

        self.min_button = QPushButton("—")
        self.min_button.setObjectName("WindowControlButton")
        self.min_button.clicked.connect(self.showMinimized)

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("CloseWindowButton")
        self.close_button.clicked.connect(self.start_fade_out)

        control_buttons_layout = QHBoxLayout()
        control_buttons_layout.setContentsMargins(0, 0, 0, 0)
        control_buttons_layout.setSpacing(5)
        control_buttons_layout.addWidget(self.min_button)
        control_buttons_layout.addWidget(self.close_button)

        header_layout.addLayout(control_buttons_layout)
        root_layout.addWidget(self.header)

        # === Main area ===
        main_area = QHBoxLayout()
        main_area.setContentsMargins(0, 0, 0, 0)
        main_area.setSpacing(0)
        root_layout.addLayout(main_area, stretch=1)

        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("SidebarFrame")
        self.sidebar_frame.setStyleSheet(f"background-color: rgba(10, 10, 10, 0.9);")
        self.sidebar_frame.setFixedWidth(0)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(25, 50, 25, 25)
        sidebar_layout.setSpacing(15)

        btn1 = QPushButton("Контрпики")
        btn1.setObjectName("SidebarButton")
        btn1.setMinimumHeight(60)
        btn1.setMinimumWidth(200)
        btn1.setCursor(Qt.PointingHandCursor)
        btn1.clicked.connect(lambda: self.set_page(0))
        sidebar_layout.addWidget(btn1)

        btn2 = QPushButton("Мета героев")
        btn2.setObjectName("SidebarButton")
        btn2.setMinimumHeight(60)
        btn2.setMinimumWidth(200)
        btn2.setCursor(Qt.PointingHandCursor)
        btn2.clicked.connect(lambda: self.set_page(1))
        sidebar_layout.addWidget(btn2)

        sidebar_layout.addStretch(1)

        version_lbl = QLabel(f"v{APP_VERSION}")
        version_lbl.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 12px;")
        version_lbl.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(version_lbl)

        main_area.addWidget(self.sidebar_frame)

        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStack")
        main_area.addWidget(self.stack, stretch=1)

        # === Page 1 ===
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(30, 40, 30, 40)
        content_layout.setSpacing(20)

        self.search_block_container = QFrame()
        self.search_block_container.setObjectName("SearchCard")
        self.search_block_container.setProperty("class", "Card")
        search_block_layout = QVBoxLayout(self.search_block_container)
        search_block_layout.setContentsMargins(20, 20, 20, 20)
        self.search_block = HeroSearchFrame(self.all_heroes, self.add_enemy, self)
        search_block_layout.addWidget(self.search_block)
        cv_controls_frame = QFrame()
        cv_controls_frame.setObjectName("CvControlsCard")
        cv_controls_frame.setProperty("class", "Card")
        cv_controls_layout = QHBoxLayout(cv_controls_frame)
        cv_controls_layout.setContentsMargins(20, 15, 20, 15)
        cv_controls_layout.setSpacing(10)

        self.auto_scan_btn = QPushButton("Автосканирование: ВЫКЛ")
        self.auto_scan_btn.setCheckable(True)
        self.auto_scan_btn.setFixedHeight(45)
        self.auto_scan_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.auto_scan_btn.setCursor(Qt.PointingHandCursor)
        self.auto_scan_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(20, 20, 20, 0.8);
                color: #9ca3af;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 12px 20px;
            }
            QPushButton:hover {
                background-color: rgba(55, 65, 81, 0.8);
                border-color: rgba(255, 255, 255, 0.2);
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: rgba(220, 38, 38, 0.25);
                border-color: #dc2626;
                color: #ffffff;
            }
            QPushButton:checked:hover {
                background-color: rgba(220, 38, 38, 0.35);
            }
        """)
        self.auto_scan_btn.clicked.connect(self._toggle_auto_scan_button)
        cv_controls_layout.addWidget(self.auto_scan_btn)

        # === ТАБЛИЧКА ВЫБОРА КОМАНДЫ ===
        self.team_selector_frame = QFrame()
        self.team_selector_frame.setObjectName("TeamSelectorCard")
        self.team_selector_frame.setProperty("class", "Card")
        self.team_selector_frame.setVisible(False)  # Скрыта по умолчанию

        team_selector_layout = QVBoxLayout(self.team_selector_frame)
        team_selector_layout.setContentsMargins(20, 15, 20, 15)
        team_selector_layout.setSpacing(10)

        team_title = QLabel("⚠️ GSI не доступен - выбери команду вручную:")
        team_title.setStyleSheet(f"color: {COLOR_TEXT_WHITE}; font-size: 13px; font-weight: bold;")
        team_selector_layout.addWidget(team_title)

        team_buttons_layout = QHBoxLayout()
        team_buttons_layout.setSpacing(10)

        self.radiant_btn = QPushButton("🌟 СВЕТ (Я слева)")
        self.radiant_btn.setFixedHeight(40)
        self.radiant_btn.setCursor(Qt.PointingHandCursor)
        self.radiant_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(34, 197, 94, 0.2);
                color: #22c55e;
                border: 2px solid #22c55e;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(34, 197, 94, 0.4);
                color: white;
            }
        """)
        self.radiant_btn.clicked.connect(lambda: self.set_manual_team('radiant'))
        team_buttons_layout.addWidget(self.radiant_btn)

        self.dire_btn = QPushButton("🔥 ТЬМА (Я справа)")
        self.dire_btn.setFixedHeight(40)
        self.dire_btn.setCursor(Qt.PointingHandCursor)
        self.dire_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(220, 38, 38, 0.2);
                color: #dc2626;
                border: 2px solid #dc2626;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(220, 38, 38, 0.4);
                color: white;
            }
        """)
        self.dire_btn.clicked.connect(lambda: self.set_manual_team('dire'))
        team_buttons_layout.addWidget(self.dire_btn)

        team_selector_layout.addLayout(team_buttons_layout)

        self.enemies_container = QFrame()
        self.enemies_container.setObjectName("EnemiesCard")
        self.enemies_container.setProperty("class", "Card")
        enemies_main_layout = QVBoxLayout(self.enemies_container)
        enemies_main_layout.setContentsMargins(20, 20, 20, 20)
        enemies_main_layout.setSpacing(10)

        self.enemies_title = QLabel("ПИК ВРАГА")
        self.enemies_title.setObjectName("TitleLabel")
        enemies_main_layout.addWidget(self.enemies_title)

        self.enemies_list_widget = QWidget()
        self.enemies_list_layout = QHBoxLayout(self.enemies_list_widget)
        self.enemies_list_layout.setContentsMargins(0, 5, 0, 5)
        self.enemies_list_layout.setSpacing(15)
        self.enemies_list_layout.addStretch(1)

        enemies_main_layout.addWidget(self.enemies_list_widget)
        self.results_container = QFrame()
        self.results_container.setObjectName("ResultsCard")
        self.results_container.setProperty("class", "Card")
        results_main_layout = QVBoxLayout(self.results_container)
        results_main_layout.setContentsMargins(20, 20, 20, 20)
        results_main_layout.setSpacing(10)

        results_title = QLabel("РЕКОМЕНДАЦИИ (ТОП-20)")
        results_title.setObjectName("TitleLabel")
        results_main_layout.addWidget(results_title)

        self.results_scroll_area = QScrollArea()
        self.results_scroll_area.setWidgetResizable(True)
        self.results_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.results_scroll_content = QWidget()
        self.results_list_layout = QVBoxLayout(self.results_scroll_content)
        self.results_list_layout.setContentsMargins(0, 10, 0, 10)
        self.results_list_layout.setSpacing(0)
        self.results_list_layout.setAlignment(Qt.AlignTop)

        self.results_scroll_area.setWidget(self.results_scroll_content)
        results_main_layout.addWidget(self.results_scroll_area)

        content_splitter = QSplitter(Qt.Vertical)
        content_splitter.setObjectName("ContentSplitter")
        content_splitter.setHandleWidth(6)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.addWidget(self.search_block_container)
        content_splitter.addWidget(cv_controls_frame)
        content_splitter.addWidget(self.team_selector_frame)
        content_splitter.addWidget(self.enemies_container)
        content_splitter.addWidget(self.results_container)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 0)
        content_splitter.setStretchFactor(2, 0)
        content_splitter.setStretchFactor(3, 1)
        content_splitter.setStretchFactor(4, 3)

        content_layout.addWidget(content_splitter)

        self.stack.addWidget(content_frame)

        # === Page 2 ===
        picker_frame = QFrame()
        picker_frame.setObjectName("PickerFrame")
        picker_layout = QVBoxLayout(picker_frame)
        picker_layout.setContentsMargins(30, 40, 30, 40)
        picker_layout.setSpacing(20)

        title_container = QFrame()
        title_container.setProperty("class", "Card")
        title_container_layout = QVBoxLayout(title_container)
        title_container_layout.setContentsMargins(25, 20, 25, 20)

        main_title = QLabel("МЕТА ГЕРОЕВ")
        main_title.setStyleSheet(f"""
            color: {COLOR_ACCENT}; 
            font-size: 24px; 
            font-weight: bold;
            letter-spacing: 3px;
        """)
        main_title.setAlignment(Qt.AlignCenter)
        title_container_layout.addWidget(main_title)

        subtitle = QLabel("Выберите позицию для просмотра лучших героев текущей меты")
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 13px;")
        subtitle.setAlignment(Qt.AlignCenter)
        title_container_layout.addWidget(subtitle)

        picker_layout.addWidget(title_container)

        roles_container = QFrame()
        roles_container.setProperty("class", "Card")
        roles_container_layout = QVBoxLayout(roles_container)
        roles_container_layout.setContentsMargins(30, 30, 30, 30)
        roles_container_layout.setSpacing(20)

        top_row = QHBoxLayout()
        top_row.setSpacing(15)
        top_row.setAlignment(Qt.AlignCenter)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(15)
        bottom_row.setAlignment(Qt.AlignCenter)

        self.role_buttons = {}

        core_roles = ["Carry", "Mider", "Offlaner"]
        support_roles = ["Support", "Hard Support"]

        for role_key in core_roles:
            display_name = ROLE_DISPLAY_NAMES.get(role_key, role_key)
            btn = RoleButton(role_key, display_name)
            btn.clicked.connect(lambda checked, r=role_key: self.on_role_selected(r))
            self.role_buttons[role_key] = btn
            top_row.addWidget(btn)

        for role_key in support_roles:
            display_name = ROLE_DISPLAY_NAMES.get(role_key, role_key)
            btn = RoleButton(role_key, display_name)
            btn.clicked.connect(lambda checked, r=role_key: self.on_role_selected(r))
            self.role_buttons[role_key] = btn
            bottom_row.addWidget(btn)

        roles_container_layout.addLayout(top_row)
        roles_container_layout.addLayout(bottom_row)

        self.picker_results_container = QFrame()
        self.picker_results_container.setProperty("class", "Card")
        self.picker_results_container.setVisible(False)
        picker_results_layout = QVBoxLayout(self.picker_results_container)
        picker_results_layout.setContentsMargins(20, 20, 20, 20)
        picker_results_layout.setSpacing(10)

        self.selected_role_label = QLabel("")
        self.selected_role_label.setObjectName("TitleLabel")
        picker_results_layout.addWidget(self.selected_role_label)

        self.picker_results_scroll = QScrollArea()
        self.picker_results_scroll.setWidgetResizable(True)
        self.picker_results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.picker_results_content = QWidget()
        self.picker_results_list_layout = QVBoxLayout(self.picker_results_content)
        self.picker_results_list_layout.setContentsMargins(0, 10, 0, 10)
        self.picker_results_list_layout.setSpacing(0)
        self.picker_results_list_layout.setAlignment(Qt.AlignTop)

        self.picker_results_scroll.setWidget(self.picker_results_content)
        picker_results_layout.addWidget(self.picker_results_scroll, stretch=1)

        picker_splitter = QSplitter(Qt.Vertical)
        picker_splitter.setObjectName("PickerSplitter")
        picker_splitter.setHandleWidth(6)
        picker_splitter.setChildrenCollapsible(False)
        picker_splitter.addWidget(roles_container)
        picker_splitter.addWidget(self.picker_results_container)
        picker_splitter.setStretchFactor(0, 1)
        picker_splitter.setStretchFactor(1, 2)

        picker_layout.addWidget(picker_splitter, stretch=1)

        bottom_panel = QHBoxLayout()
        bottom_panel.setContentsMargins(0, 10, 0, 0)

        note = QLabel("Данные обновляются автоматически с OpenDota API")
        note.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 11px;")
        bottom_panel.addWidget(note)

        bottom_panel.addStretch()

        self.refresh_cache_btn = QPushButton("Обновить данные")
        self.refresh_cache_btn.setObjectName("RefreshCacheButton")
        self.refresh_cache_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_cache_btn.clicked.connect(lambda: self._start_cache_refresh(force=True, reason="manual"))
        bottom_panel.addWidget(self.refresh_cache_btn)

        picker_layout.addLayout(bottom_panel)

        self.stack.addWidget(picker_frame)

        self.render_enemies()
        self.calculate_counters()

        # GSI кеш (оптимизация - нет лагов!)
        self._gsi_team_cache = None
        self._gsi_last_check = 0
        self._gsi_cache_duration = 3.0  # Кеш на 3 секунды        # === SMART PICK DETECTOR ===
        self.pick_detector = PickDetector()
        self.pick_detector.signals.pick_detected.connect(self.on_pick_detected)
        self.pick_detector.signals.status.connect(self.on_pick_status)

        self.pick_monitor_timer = QTimer()
        self.pick_monitor_timer.timeout.connect(self._pick_monitor_tick)

        self.sidebar_anim = QPropertyAnimation(self.sidebar_frame, b"maximumWidth")
        self.sidebar_anim.setDuration(250)
        self.sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.sidebar_expanded = False
        self.sidebar_frame.setMaximumWidth(0)

        self.results_container_anim = None

        QTimer.singleShot(500, self._check_whats_new)
        QTimer.singleShot(2500, lambda: self._start_cache_refresh(force=False, reason="startup"))

        # Инициализируем CV сканер
        self.setup_cv_scanner()

        size_grip = QSizeGrip(central_widget)
        size_grip.setObjectName("WindowSizeGrip")
        size_grip.setFixedSize(16, 16)
        root_layout.addWidget(size_grip, alignment=Qt.AlignRight | Qt.AlignBottom)

    def _start_cache_refresh(self, force: bool = False, reason: str = ""):
        if self._refresh_in_progress:
            return

        if not force and is_cache_fresh():
            return

        self._refresh_in_progress = True

        if hasattr(self, 'refresh_cache_btn') and self.refresh_cache_btn:
            self.refresh_cache_btn.setEnabled(False)
            self.refresh_cache_btn.setText("Загрузка...")
            self.refresh_cache_btn.setText("Загрузка...")

        def worker():
            data = fetch_opendota_hero_stats(timeout=(4, 16), total_retries=3)
            if data:
                save_json_file(OPENDOTA_CACHE_FILE, data)
                if len(data) > 0 and "id" in data[0]:
                    mark_cache("net")
                else:
                    mark_cache("static", note="fallback-data")
                self._signals.done.emit(True, data, "ok")
            else:
                self._signals.done.emit(False, None, "no-connection")

        threading.Thread(target=worker, daemon=True).start()

    def _on_cache_refresh_done(self, success: bool, data, message: str):
        self._refresh_in_progress = False

        if hasattr(self, 'refresh_cache_btn') and self.refresh_cache_btn:
            if success:
                self.refresh_cache_btn.setText("Обновлено!")
            else:
                self.refresh_cache_btn.setText("Ошибка")
                # Показываем fallback данные
                if not self.opendota_cache:
                    print("[META] 📦 Используем встроенные данные")
                    self.opendota_cache = get_static_fallback()

        if success and data:
            self.opendota_cache = data
            if self.selected_role:
                try:
                    self.fetch_role_heroes(self.selected_role)
                except Exception:
                    pass

        QTimer.singleShot(1600, self._reset_refresh_button)

    def _reset_refresh_button(self):
        if hasattr(self, 'refresh_cache_btn') and self.refresh_cache_btn:
            self.refresh_cache_btn.setEnabled(True)
            self.refresh_cache_btn.setText("Обновить данные")

    def _check_whats_new(self):
        if should_show_whats_new():
            dialog = WhatsNewDialog(self)
            dialog.exec()

    def toggle_sidebar(self):
        target = 260 if not self.sidebar_expanded else 0
        self.sidebar_anim.stop()
        self.sidebar_anim.setStartValue(self.sidebar_frame.maximumWidth())
        self.sidebar_anim.setEndValue(target)
        self.sidebar_anim.start()
        self.sidebar_expanded = not self.sidebar_expanded


    def set_page(self, index: int):
        self.stack.setCurrentIndex(index)
        if self.sidebar_expanded:
            self.toggle_sidebar()
        if index == 1:
            self._start_cache_refresh(force=False, reason="open-meta")

    def start_fade_out(self):
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(QApplication.quit)
        self.fade_anim.start()

    def closeEvent(self, event: QCloseEvent):
        QApplication.quit()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            edges = self._get_resize_edges(event.position().toPoint())
            if any(edges):
                self._resizing = True
                self._resize_edges = edges
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                event.accept()
                return
            self.old_pos = event.globalPosition().toPoint()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._resizing and self._resize_start_geom and self._resize_start_pos:
            self._resize_window(event.globalPosition().toPoint())
            event.accept()
            return
        self._update_cursor(event.position().toPoint())
        if event.buttons() == Qt.LeftButton and self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self._resizing:
                self._resizing = False
                self._resize_edges = None
                self._resize_start_pos = None
                self._resize_start_geom = None
            self.old_pos = None
            event.accept()
        super().mouseReleaseEvent(event)

    def _get_resize_edges(self, pos: QPoint) -> tuple[bool, bool, bool, bool]:
        rect = self.rect()
        left = pos.x() <= self._resize_margin
        right = pos.x() >= rect.width() - self._resize_margin
        top = pos.y() <= self._resize_margin
        bottom = pos.y() >= rect.height() - self._resize_margin
        return left, right, top, bottom

    def _update_cursor(self, pos: QPoint):
        if self._resizing:
            return
        left, right, top, bottom = self._get_resize_edges(pos)
        if (left and top) or (right and bottom):
            self.setCursor(Qt.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.SizeHorCursor)
        elif top or bottom:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def _resize_window(self, global_pos: QPoint):
        if not self._resize_edges or not self._resize_start_geom or not self._resize_start_pos:
            return
        left, right, top, bottom = self._resize_edges
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        geom = QRect(self._resize_start_geom)

        if left:
            new_left = geom.left() + dx
            max_left = geom.right() - self.minimumWidth()
            geom.setLeft(min(new_left, max_left))
        if right:
            geom.setRight(max(geom.right() + dx, geom.left() + self.minimumWidth()))
        if top:
            new_top = geom.top() + dy
            max_top = geom.bottom() - self.minimumHeight()
            geom.setTop(min(new_top, max_top))
        if bottom:
            geom.setBottom(max(geom.bottom() + dy, geom.top() + self.minimumHeight()))

        self.setGeometry(geom)

    def on_role_selected(self, role_key):
        self.selected_role = role_key
        display_name = ROLE_DISPLAY_NAMES.get(role_key, role_key)
        self.selected_role_label.setText(f"ТОП ГЕРОИ: {display_name.upper()}")

        for key, btn in self.role_buttons.items():
            btn.update_style(key == role_key)

        if not self.picker_results_container.isVisible():
            self.picker_results_container.setVisible(True)
            self.picker_results_container.setMaximumHeight(0)

            self.results_container_anim = QPropertyAnimation(self.picker_results_container, b"maximumHeight")
            self.results_container_anim.setDuration(1000)
            self.results_container_anim.setStartValue(0)
            self.results_container_anim.setEndValue(2000)
            self.results_container_anim.setEasingCurve(QEasingCurve.OutCubic)
            self.results_container_anim.start()

            QTimer.singleShot(1050, lambda: self.fetch_role_heroes(role_key))
        else:
            self.fetch_role_heroes(role_key)

        self._start_cache_refresh(force=False, reason="role-click")

    def fetch_role_heroes(self, role_key):
                # Защита от None
        if self.opendota_cache is None:
            self.opendota_cache = get_static_fallback()
            print("[META] 📦 Используем встроенные данные (кеш пуст)")

        while self.picker_results_list_layout.count() > 0:
            item = self.picker_results_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            del item

        if self.opendota_cache is None:
            cached_data = load_opendota_cache(prefer_appdata=True)
            if cached_data:
                self.opendota_cache = cached_data
            else:
                loading = QLabel("Загрузка данных с OpenDota...")
                loading.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 14px; padding: 20px;")
                loading.setAlignment(Qt.AlignCenter)
                self.picker_results_list_layout.addWidget(loading)
                QApplication.processEvents()

                def set_status(t: str):
                    loading.setText(t)
                    QApplication.processEvents()

                data = fetch_opendota_hero_stats(status_cb=set_status, timeout=(4, 16), total_retries=3)
                if not data:
                    self._show_error("Нет подключения к OpenDota. Используется кэш/офлайн режим.")
                    return
                self.opendota_cache = data
                save_json_file(OPENDOTA_CACHE_FILE, self.opendota_cache)
                if len(data) > 0 and "id" in data[0]:
                    mark_cache("net")
                else:
                    mark_cache("static")

        role_heroes = HERO_ROLES.get(role_key, [])
        if not role_heroes:
            self._show_error("Нет героев для этой роли")
            return

        results = []
        for hero_data in self.opendota_cache:
            hero_name = (hero_data.get("name") or "").replace("npc_dota_hero_", "")

            hero_matches_role = False
            if hero_name in role_heroes:
                hero_matches_role = True
            elif hero_name.replace("_", "-") in role_heroes:
                hero_matches_role = True
            elif hero_name.replace("_", "") in role_heroes:
                hero_matches_role = True
            elif hero_name in HERO_SLUG_MAP:
                mapped = HERO_SLUG_MAP[hero_name]
                if mapped in role_heroes or mapped.replace("-", "_") in role_heroes:
                    hero_matches_role = True

            if not hero_matches_role:
                continue

            total_pick = 0
            total_win = 0
            for i in range(1, 9):
                total_pick += hero_data.get(f"{i}_pick", 0) or 0
                total_win += hero_data.get(f"{i}_win", 0) or 0

            if total_pick < 100:
                pro_pick = hero_data.get("pro_pick", 0) or 0
                pro_win = hero_data.get("pro_win", 0) or 0
                if pro_pick > total_pick:
                    total_pick = pro_pick
                    total_win = pro_win

            if total_pick < 50:
                continue

            winrate = (total_win / total_pick) * 100.0 if total_pick > 0 else 0

            results.append({
                "data": hero_data,
                "slug": hero_name,
                "winrate": winrate,
                "picks": total_pick
            })

        while self.picker_results_list_layout.count() > 0:
            item = self.picker_results_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            del item

        if not results:
            self._show_error("Нет данных для этой роли")
            return

        results.sort(key=lambda x: x["winrate"], reverse=True)

        self.picker_animation_timer.stop()
        self.picker_animated_results = []

        for idx, hero_info in enumerate(results[:15], 1):
            row = self._create_picker_result_row(idx, hero_info)
            self.picker_results_list_layout.addWidget(row)
            self.picker_animated_results.append(row)

        self.picker_animation_timer.start(80)
        self.picker_results_list_layout.addStretch(1)

    def _show_error(self, message):
        while self.picker_results_list_layout.count() > 0:
            item = self.picker_results_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            del item
        err = QLabel(message)
        err.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 14px; padding: 20px;")
        err.setAlignment(Qt.AlignCenter)
        self.picker_results_list_layout.addWidget(err)

    def _create_picker_result_row(self, rank, hero_info):
        row = ResultRow()
        row.setProperty("class", "ResultRowOdd" if rank % 2 != 0 else "ResultRowEven")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(15, 10, 15, 10)
        row_layout.setSpacing(10)

        rank_color = COLOR_ACCENT if rank <= 3 else COLOR_TEXT_GRAY
        rank_lbl = QLabel(f"{rank:02d}.")
        rank_lbl.setFixedWidth(35)
        rank_lbl.setStyleSheet(f"color: {rank_color}; font-weight: bold; font-size: 15px;")
        row_layout.addWidget(rank_lbl)

        hero_slug = hero_info["slug"]
        pixmap = None

        pixmap = get_hero_icon_from_local(hero_slug, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)
        if not pixmap and hero_slug in HERO_SLUG_MAP:
            mapped_slug = HERO_SLUG_MAP[hero_slug]
            pixmap = get_hero_icon_from_local(mapped_slug, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)
        if not pixmap:
            alt_slug = hero_slug.replace("_", "-")
            pixmap = get_hero_icon_from_local(alt_slug, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)
        if not pixmap:
            alt_slug = hero_slug.replace("_", "")
            pixmap = get_hero_icon_from_local(alt_slug, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)

        if pixmap:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(pixmap)
            icon_lbl.setFixedSize(QSize(ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE))
        else:
            icon_lbl = self.create_placeholder_icon_label(hero_slug, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)

        row_layout.addWidget(icon_lbl)

        display_name = hero_info["data"].get("localized_name", hero_slug.replace("-", " ").title())
        name_lbl = QLabel(display_name)
        name_lbl.setFont(QFont(FONT_FAMILY_MAIN, 14))
        name_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        row_layout.addWidget(name_lbl)

        row_layout.addStretch(1)

        picks_lbl = QLabel(f"{hero_info['picks']} игр")
        picks_lbl.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 12px;")
        picks_lbl.setFixedWidth(80)
        row_layout.addWidget(picks_lbl)

        wr = hero_info["winrate"]
        wr_color = COLOR_SUCCESS_GREEN if wr >= 50 else COLOR_DANGER_RED
        wr_lbl = QLabel(f"{wr:.1f}%")
        wr_lbl.setStyleSheet(f"color: {wr_color}; font-weight: bold; font-size: 17px;")
        wr_lbl.setFixedWidth(70)
        wr_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row_layout.addWidget(wr_lbl)

        return row


    def setup_cv_scanner(self):
        """Инициализирует CV сканер"""
        # ⚠️ ВАЖНО: API ключи должны быть в переменных окружения или конфиге!
        # Не храните ключи в коде! Используйте: os.getenv('CV_API_KEY')
        api_keys = []

        # Попытка загрузить из переменных окружения
        env_key = os.getenv('CV_API_KEY')
        if env_key:
            api_keys = [k.strip() for k in env_key.split(',') if k.strip()]

        # Fallback: если нет в env, можно использовать конфиг файл
        if not api_keys:
            config_path = os.path.join(get_app_data_path(), 'cv_config.json')
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        api_keys = config.get('api_keys', [])
                except Exception as e:
                    print(f"[CV] Ошибка загрузки конфига: {e}")

        if not api_keys:
            print("[CV] CV сканер будет работать в ограниченном режиме.")

        self.cv_scanner = CVScanner(api_keys)

        # Подключаем сигналы
        self.cv_scanner.signals.progress.connect(self.on_scan_progress)
        self.cv_scanner.signals.heroes_found.connect(self.on_heroes_found)
        self.cv_scanner.signals.error.connect(self.on_scan_error)

        # === ПРОВЕРЬ ЧТО ТУТ НЕТ НИЧЕГО ЛИШНЕГО! ===
        # self.cv_scanner.signals.scanning_finished.connect(???)  # ← НЕ ДОЛЖНО БЫТЬ!

        # Настройка таймера
        self.auto_scan_timer = QTimer()
        self.auto_scan_timer.timeout.connect(self._auto_scan_tick)
        self.scan_interval_ms = 4000
        self.waiting_for_game = False

        print("[SETUP] ✅ CV Scanner готов, интервал 4 сек")

    def on_scan_progress(self, message):
        """Обработчик прогресса сканирования (с кешированием!)"""

        # === КЕШИРОВАНИЕ: Не обновляем UI если сообщение не изменилось ===
        if hasattr(self, '_last_progress_message') and self._last_progress_message == message:
            return  # Пропускаем обновление UI

        self._last_progress_message = message

        clean_msg = message.replace("🔬 ", "").replace("🔍 ", "")
        print(f"[CV] {clean_msg}")

        if hasattr(self, 'search_block'):
            self.search_block.status_label.setText(message)

            # Красная подсветка при перекрытии
            if "ПЕРЕКРЫВАЕТ" in message:
                self.search_block.status_label.setStyleSheet(f"""
                    color: {COLOR_ACCENT};
                    font-size: 13px;
                    font-weight: bold;
                    background-color: rgba(220, 38, 38, 0.2);
                    padding: 5px;
                    border-radius: 4px;
                """)
            else:
                self.search_block.status_label.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; font-size: 13px;")

    def on_heroes_found(self, heroes, confidence):
        """Умная обработка - ДОБАВЛЯЕМ новых, ПРОДОЛЖАЕМ сканирование, ОБНОВЛЯЕМ базу детектора"""
        print(f"[CV] Найдено: {heroes} [{confidence}]")

        added_count = 0
        for hero in heroes:
            if hero not in self.selected_enemies and len(self.selected_enemies) < 5:
                self.add_enemy(hero)
                added_count += 1

        total = len(self.selected_enemies)

        if added_count > 0:
            try:
                self.play_success_sound()
            except:
                pass

            print(f"[CV] Добавлено: {added_count}, Всего: {total}/5")

            # ВАЖНО: Обновляем базу детектора пиков после успешного сканирования
            # Это нужно для детекции следующего пика в формате 2-2-1
            if self.pick_detector.monitoring and added_count > 0:
                # Обновляем базу с небольшой задержкой, чтобы герои успели появиться на экране
                QTimer.singleShot(800, self._update_pick_detector_base)

            if total < 5:
                remain = 5 - total
                self.on_scan_progress(f" +{added_count} герой! Осталось: {remain}")
                # НЕ ОСТАНАВЛИВАЕМ! Автосканирование продолжится
            else:
                self.on_scan_progress("Все 5 врагов найдены!")
                # Останавливаем детектор пиков если все найдено
                if self.pick_detector.monitoring:
                    self.pick_detector.stop_monitoring()
        else:
            # Ничего нового не нашли
            print(f"[CV] Все найденные уже добавлены ({total}/5)")
            if total < 5:
                self.on_scan_progress(f"Ожидание новых героев... ({total}/5)")
                # Обновляем базу даже если ничего нового не найдено
                # (герои могут быть в процессе появления)
                if self.pick_detector.monitoring:
                    QTimer.singleShot(1000, self._update_pick_detector_base)

    def on_scan_error(self, error):
        """Обработчик ошибки сканирования"""
        print(f"[CV ERROR] {error}")
        if hasattr(self, 'search_block'):
            self.search_block.status_label.setText(f"❌ Ошибка: {error}")

    def start_cv_scan(self):
        """Кнопка: Сканировать сейчас с учетом команды"""
        # Получаем команду из GSI
        player_team = self.get_player_team_from_gsi()
        if player_team:
            self.on_scan_progress(f"Команда: {player_team.upper()}")

        # Сворачиваем окно
        # Запускаем сканирование
        self.cv_scanner.player_team = player_team
        self.cv_scanner.scan_once(delay=2)

    def toggle_auto_scan(self, enabled):
        """Переключатель автосканирования (С ПОЛНЫМ СБРОСОМ)"""
        if enabled:
            # === ПРОВЕРКА GSI КОНФИГА ===
            import string
            from PySide6.QtWidgets import QMessageBox
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            gsi_found = False
            gsi_path = None

            for drive in drives:
                paths = [
                    "Program Files (x86)\\Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                ]
                for path in paths:
                    full_path = os.path.join(drive, path)
                    if os.path.exists(full_path):
                        gsi_found = True
                        gsi_path = full_path
                        print(f"[GSI] ✅ Конфиг найден: {full_path}")
                        break
                if gsi_found:
                    break

            if not gsi_found:
                print("[GSI] ⚠️ КОНФИГ НЕ НАЙДЕН - СОЗДАЮ АВТОМАТИЧЕСКИ")
                # Пытаемся создать через GSI сервер
                try:
                    # GSI сервер уже имеет метод auto_setup_gsi
                    # Вызываем его повторно для гарантии
                    from __main__ import start_gsi_server
                    # Инициализируем GSI сервер заново
                    temp_gsi = GSIServer()
                    print("[GSI] 📝 Конфиг создан автоматически")
                    print("[GSI] 🔄 ПЕРЕЗАПУСТИ DOTA 2 для активации GSI!")

                    # ПОКАЗЫВАЕМ ПРЕДУПРЕЖДЕНИЕ
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Готово!")
                    msg.setText("Всё готово к работе")
                    msg.setInformativeText(
                        "Чтобы изменения вступили в силу:\n\n"
                        "1 Полностью закрой Dota 2\n"
                        "2 Запусти игру заново\n\n"
                        "После перезапуска MetaMind начнёт работать автоматически."
                    )

                    msg.setStyleSheet("""
                        QMessageBox {
                            background-color: #0f172a;
                        }
                        QMessageBox QLabel {
                            color: #e5e7eb;
                            font-size: 14px;
                        }
                        QMessageBox QLabel#qt_msgbox_label {
                            font-size: 16px;
                            font-weight: bold;
                            color: #ffffff;
                        }
                        QPushButton {
                            background-color: #22c55e;
                            color: #0f172a;
                            border: none;
                            border-radius: 6px;
                            padding: 8px 24px;
                            font-weight: bold;
                        }
                        QPushButton:hover {
                            background-color: #4ade80;
                        }
                    """)

                    msg.exec()

                    self.on_scan_progress("⚠️ GSI создан - перезапусти Dota 2!")
                except Exception as e:
                    print(f"[GSI] ❌ Ошибка создания конфига: {e}")
                    self.on_scan_progress("❌ GSI конфиг не найден - создай вручную")

            # === ПРОВЕРКА GSI КОНФИГА ===
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            gsi_found = False
            gsi_path = None

            for drive in drives:
                paths = [
                    "Program Files (x86)\\Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                ]
                for path in paths:
                    full_path = os.path.join(drive, path)
                    if os.path.exists(full_path):
                        gsi_found = True
                        gsi_path = full_path
                        print(f"[GSI] ✅ Конфиг найден: {full_path}")
                        break
                if gsi_found:
                    break

            if not gsi_found:
                print("[GSI] ⚠️ КОНФИГ НЕ НАЙДЕН - СОЗДАЮ АВТОМАТИЧЕСКИ")
                # Пытаемся создать через GSI сервер
                try:
                    # GSI сервер уже имеет метод auto_setup_gsi
                    # Вызываем его повторно для гарантии
                    from __main__ import start_gsi_server
                    # Инициализируем GSI сервер заново
                    temp_gsi = GSIServer()
                    print("[GSI] 📝 Конфиг создан автоматически")
                    print("[GSI] 🔄 ПЕРЕЗАПУСТИ DOTA 2 для активации GSI!")
                    self.on_scan_progress("⚠️ GSI создан - перезапусти Dota 2!")
                except Exception as e:
                    print(f"[GSI] ❌ Ошибка создания конфига: {e}")
                    self.on_scan_progress("❌ GSI конфиг не найден - создай вручную")

            # Проверяем что GSI конфиг существует
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            gsi_found = False
            for drive in drives:
                paths = [
                    "Program Files (x86)\\Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                ]
                for path in paths:
                    full_path = os.path.join(drive, path)
                    if os.path.exists(full_path):
                        gsi_found = True
                        print(f"[GSI] ✅ Конфиг найден: {full_path}")
                        break
                if gsi_found:
                    break

            if not gsi_found:
                print("[GSI] ⚠️ КОНФИГ НЕ НАЙДЕН!")
                print("[GSI] 📝 Перезапусти приложение для автосоздания конфига")
                print("[GSI] 💡 Или создай файл вручную в папке Dota 2/cfg/gamestate_integration/")
                self.on_scan_progress("⚠️ GSI конфиг не найден - автосканирование ограничено")

            # Проверяем что GSI конфиг существует
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            gsi_found = False
            for drive in drives:
                paths = [
                    "Program Files (x86)\\Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                    "Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration\\gamestate_integration_metamind.cfg",
                ]
                for path in paths:
                    full_path = os.path.join(drive, path)
                    if os.path.exists(full_path):
                        gsi_found = True
                        print(f"[GSI] ✅ Конфиг найден: {full_path}")
                        break
                if gsi_found:
                    break

            if not gsi_found:
                print("[GSI] ⚠️ КОНФИГ НЕ НАЙДЕН!")
                print("[GSI] 📝 Перезапусти приложение для автосоздания конфига")
                print("[GSI] 💡 Или создай файл вручную в папке Dota 2/cfg/gamestate_integration/")
                self.on_scan_progress("⚠️ GSI конфиг не найден - автосканирование ограничено")

            # ВКЛЮЧАЕМ
            self.cv_scanner.auto_scan_enabled = True
            self.cv_scanner.player_team = None

            # ПОЛНЫЙ СБРОС: Сбрасываем команду в pick_detector (чтобы не запоминалась прошлая игра)
            self.pick_detector.player_team = None
            self.pick_detector.stop_monitoring()

            # Сбрасываем GSI кеш
            self._gsi_team_cache = None
            self._gsi_last_check = 0

            # Проверяем наличие героев на экране перед запуском детектора пиков
            self.on_scan_progress("Проверка наличия героев на экране...")

            # Сбрасываем кеш проверки героев для свежего результата
            if hasattr(self.cv_scanner, '_heroes_check_cache'):
                self.cv_scanner._heroes_check_cache = None
                self.cv_scanner._heroes_check_time = 0

            # Быстрая проверка: есть ли герои на экране? (без кеша для немедленного результата)
            has_heroes = self.cv_scanner.check_heroes_on_screen(force_check=True)

            if has_heroes:
                # Герои найдены - можно запускать детектор пиков
                team = self.get_team_from_gsi_cached()
                if team:
                    self.cv_scanner.player_team = team
                    self.pick_detector.set_team(team)
                    self.pick_detector.start_monitoring()
                    self.pick_monitor_timer.start(300)  # Проверка каждые 300ms
                    print(f"[PICK] ✅ Детектор пиков запущен (команда: {team})")
                    self.on_scan_progress(f"Автосканирование включено (GSI: {team.upper()})")
                else:
                    # Команда еще не определена - запустим детектор позже когда команда определится
                    # Но сразу запускаем периодическое сканирование, чтобы не пропустить героев
                    print(f"[PICK] ⏳ Команда не определена, ждем GSI (сканируем весь экран)...")
                    self.on_scan_progress("Ожидание определения команды...")
            else:
                # Героев нет - игра еще не началась, детектор не запускаем
                print(f"[PICK] ⏳ Героев на экране нет, игра еще не началась")
                self.on_scan_progress("Ожидание начала игры...")

            # Запускаем быстрый SIFT loop (2 секунды - быстрая реакция на начало игры)
            self.auto_scan_timer.start(2000)
            print(f"[TOGGLE] ✅ Быстрый SIFT loop ВКЛЮЧЕН (2 сек)")

        else:
            # ВЫКЛЮЧАЕМ + ПОЛНЫЙ СБРОС
            self.cv_scanner.auto_scan_enabled = False
            self.cv_scanner.player_team = None

            # ПОЛНЫЙ СБРОС: Останавливаем и сбрасываем детектор пиков
            self.pick_detector.stop_monitoring()
            self.pick_detector.player_team = None  # Сбрасываем команду
            self.pick_monitor_timer.stop()

            # Сбрасываем GSI кеш
            self._gsi_team_cache = None
            self._gsi_last_check = 0

            # Сбрасываем кеш проверки героев
            if hasattr(self.cv_scanner, '_heroes_check_cache'):
                self.cv_scanner._heroes_check_cache = None
                self.cv_scanner._heroes_check_time = 0

            self.auto_scan_timer.stop()
            print(f"[TOGGLE] ⛔ Автосканирование ВЫКЛЮЧЕНО (полный сброс состояния)")

            self.on_scan_progress("Автосканирование остановлено")

    def on_pick_detected(self):
        """Вызывается когда PickDetector обнаружил изменение (пик героя)"""
        total = len(self.selected_enemies)

        if total >= 5:
            print("[PICK] ✅ Уже 5/5 героев, пропускаем сканирование")
            self.pick_detector.stop_monitoring()
            return

        print(f"[PICK] ПИК ОБНАРУЖЕН! Запускаем сканирование... ({total}/5)")
        self.on_scan_progress(f" Пик обнаружен! Сканирую... ({total}/5)")

        # НЕ минимизируем окно автоматически - пользователь сам управляет окном
        # Проверяем только перекрытие, и только тогда минимизируем
        if self.isVisible() and self.check_scan_area_overlap():
            print("[PICK] ⚠️ Окно мешает сканированию, сворачиваем")
            self.showMinimized()

        # Запускаем сканирование БЕЗ задержки (пик уже произошел)
        # База детектора будет обновлена в on_heroes_found после сканирования
        if not self.cv_scanner.is_scanning:
            self.cv_scanner.scan_once(delay=0)
        else:
            print("[PICK] ⏳ Сканирование уже идет, пропускаем (дождемся завершения)")

    def _update_pick_detector_base(self):
        """Обновляет базовое изображение детектора пиков после сканирования"""
        if self.pick_detector.monitoring and self.pick_detector.monitor_region:
            try:
                # Захватываем текущее состояние для следующего пика
                screenshot = ImageGrab.grab(bbox=self.pick_detector.monitor_region)
                screenshot = screenshot.resize(SCAN_THUMB_SIZE, Image.Resampling.LANCZOS)
                screenshot_gray = screenshot.convert('L')

                self.pick_detector.last_screenshot = screenshot_gray
                print("[PICK] ✅ База обновлена для следующего пика")
            except Exception as e:
                print(f"[PICK] ⚠️ Ошибка обновления базы: {e}")

    def on_pick_status(self, message):
        """Обработчик статуса детектора пиков"""
        print(f"[PICK STATUS] {message}")

    def _pick_monitor_tick(self):
        """Тик таймера мониторинга пиков (каждые 300ms)"""
        # Проверяем изменения только если автосканирование включено
        if not self.cv_scanner.auto_scan_enabled:
            return

        # Проверяем команду и обновляем детектор если нужно
        if not self.pick_detector.player_team:
            team = self.get_team_from_gsi_cached()
            if team:
                # Проверяем наличие героев на экране перед запуском детектора
                has_heroes = self.cv_scanner.check_heroes_on_screen(force_check=False)
                if has_heroes:
                    self.cv_scanner.player_team = team
                    self.pick_detector.set_team(team)
                    if not self.pick_detector.monitoring:
                        self.pick_detector.start_monitoring()
                    print(f"[PICK] ✅ Команда определена: {team}, детектор запущен")
                else:
                    # Героев нет - не запускаем детектор пока
                    return

        # Проверяем изменения на экране (только если детектор запущен)
        if self.pick_detector.monitoring:
            self.pick_detector.check_for_change()

    def check_scan_area_overlap(self):
        """Проверяет перекрывает ли окно область сканирования (ПРОСТАЯ ЛОГИКА)"""
        if not self.isVisible():
            return False

        try:
            # ПРОСТАЯ ЛОГИКА:
            # Портреты героев находятся в верхних 120px экрана
            # Перекрывает только если окно РЕАЛЬНО высоко (top < 120px)

            window_top = self.y()

            # Порог: верхние 120px экрана (реально мешает видеть портреты)
            CRITICAL_ZONE = 120

            is_overlapping = window_top < CRITICAL_ZONE

            if is_overlapping:
                print(f"[OVERLAP] ⚠️ Окно СЛИШКОМ ВЫСОКО! top={window_top} (порог: {CRITICAL_ZONE})")
            else:
                            return is_overlapping

        except Exception as e:
            print(f"[OVERLAP] Ошибка: {e}")
            return False

    def get_team_from_gsi_cached(self):
        """ОПТИМИЗИРОВАННАЯ проверка GSI с кешем и сбросом старых данных"""
        current_time = time.time()

        # ВАЖНО: Если кеш старше 30 секунд - сбрасываем (возможно старая игра)
        if self._gsi_team_cache and self._gsi_last_check > 0:
            time_since_check = current_time - self._gsi_last_check
            if time_since_check > 60.0:
                print(f"[GSI] ⚠️ Кеш команды устарел ({time_since_check:.1f} сек), сбрасываем")
                self._gsi_team_cache = None
                self._gsi_last_check = 0

        # Проверяем кеш (если меньше 3 сек - возвращаем кеш)
        if self._gsi_team_cache and (current_time - self._gsi_last_check) < self._gsi_cache_duration:
            return self._gsi_team_cache

        # Кеш устарел - делаем запрос
        try:
            response = requests.get('http://localhost:3000/team', timeout=0.3)
            if response.status_code == 200:
                data = response.json()
                team = data.get('team')

                # Обновляем кеш только если команда валидна
                if team in ['radiant', 'dire']:
                    self._gsi_team_cache = team
                    self._gsi_last_check = current_time
                    print(f"[GSI] ✅ Команда обновлена: {team}")
                else:
                    # Команда не определена - сбрасываем кеш
                    if self._gsi_team_cache:
                        print(f"[GSI] ⚠️ Команда стала None, сбрасываем кеш")
                    self._gsi_team_cache = None
                    self._gsi_last_check = 0

                return self._gsi_team_cache
        except Exception as e:
            # Если GSI недоступен долго - сбрасываем кеш
            if self._gsi_last_check > 0 and (current_time - self._gsi_last_check) > 60.0:
                print(f"[GSI] ⚠️ GSI недоступен >60 сек, сбрасываем кеш")
                self._gsi_team_cache = None
                self._gsi_last_check = 0
            pass

        # Ошибка - возвращаем старый кеш (если он не слишком старый)
        return self._gsi_team_cache

    def _auto_scan_tick(self):
        """БЫСТРЫЙ SIFT LOOP с улучшенной логикой продолжения после пиков"""

        # Проверка 1: Включено?
        if not self.cv_scanner.auto_scan_enabled:
            return

        # === ШАГ 1: ПРОВЕРКА КОМАНДЫ (СНАЧАЛА!) ===
        # Без команды от GSI - не проверяем героев (экономим ресурсы)
        if not self.cv_scanner.player_team:
            team = self.get_team_from_gsi_cached()
            if not team:
                # Команда не определена - просто ждём
                self.on_scan_progress("Ожидание игры...")
                return  # НЕ СПАМИМ проверками героев

            # Команда получена! Сохраняем
            self.cv_scanner.player_team = team
            team_name = "СВЕТ (слева)" if team == "radiant" else "ТЬМА (справа)"
            print(f"[AUTO] ✅ Команда определена: {team_name}")

        # === ШАГ 2: ПРОВЕРКА ГЕРОЕВ НА ЭКРАНЕ ===
        # Теперь, когда команда есть, проверяем героев
        has_heroes = self.cv_scanner.check_heroes_on_screen(force_check=False)

        if not has_heroes:
            # Героев нет - ждём начала игры
            team_name = "СВЕТ" if self.cv_scanner.player_team == "radiant" else "ТЬМА"
            self.on_scan_progress(f"Команда: {team_name}, ожидание начала игры...")

            # Настраиваем детектор пиков заранее
            if not self.pick_detector.player_team:
                self.pick_detector.set_team(self.cv_scanner.player_team)
                print(f"[AUTO] 📍 Детектор настроен, ожидание героев...")
            return  # Не сканируем пока героев нет

        # === ШАГ 3: ГЕРОИ + КОМАНДА = ЗАПУСК! ===
        # Настраиваем и запускаем детектор пиков
        if not self.pick_detector.player_team:
            self.pick_detector.set_team(self.cv_scanner.player_team)
            self.pick_detector.start_monitoring()
            self.pick_monitor_timer.start(300)
            team_name = "СВЕТ (слева)" if self.cv_scanner.player_team == "radiant" else "ТЬМА (справа)"
            print(f"[AUTO] ✅ Детектор запущен: {team_name}")
        elif not self.pick_detector.monitoring:
            self.pick_detector.start_monitoring()
            self.pick_monitor_timer.start(300)

        team_name = "СВЕТ" if self.cv_scanner.player_team == "radiant" else "ТЬМА"
        self.on_scan_progress(f"GSI: {team_name}, сканирование...")

        # ВАЖНО: Проверяем команду ПЕРЕД проверкой героев
        # Без команды от GSI - не проверяем вообще (экономим ресурсы)
        if not self.cv_scanner.player_team:
            team = self.get_team_from_gsi_cached()
            if not team:
                # Команда не определена - просто ждём, не спамим проверками
                self.on_scan_progress("Ожидание игры...")
                return
            # Команда получена!
            self.cv_scanner.player_team = team

        # Проверка 2: Уже сканирует? Продолжаем ждать (не останавливаем таймер)
        if self.cv_scanner.is_scanning:
            total = len(self.selected_enemies)
            print(f"[AUTO] ⏳ Сканирование в процессе... ({total}/5)")
            return  # Пропускаем этот тик, но таймер продолжит работу

        # Проверка 4: Все 5 найдены?
        total = len(self.selected_enemies)
        if total >= 5:
            print("[AUTO] ✅ 5/5 - ОСТАНАВЛИВАЕМ")
            self.on_scan_progress("✅ ВСЕ 5 ВРАГОВ НАЙДЕНЫ!")
            self.toggle_auto_scan(False)
            return

        # Герои на экране - запускаем сканирование
        print(f"[AUTO] 🔄 Периодический скан... ({total}/5)")
        self.on_scan_progress(f"🔍 Сканирование... ({total}/5)")

        # НЕ минимизируем окно автоматически - только если оно мешает сканированию
        # Проверяем перекрытие и только тогда минимизируем
        if self.isVisible() and self.check_scan_area_overlap():
            print("[AUTO] ⚠️ Окно мешает сканированию, сворачиваем")
            self.showMinimized()

        # БЫСТРЫЙ СКАН БЕЗ ЗАДЕРЖКИ
        # Важно: сканирование продолжается даже если детектор пиков уже сработал
        # Это обеспечивает обнаружение всех героев в формате 2-2-1
        self.cv_scanner.scan_once(delay=0)

    def load_data(self):
        hero_data = load_json_file(DATA_FILE)
        am_counters = load_json_file(AM_COUNTERS_FILE)
        return hero_data, am_counters

    def add_enemy(self, hero_slug):
        if hero_slug in self.all_heroes and len(
                self.selected_enemies) < MAX_ENEMIES and hero_slug not in self.selected_enemies:
            self.selected_enemies.append(hero_slug)
            self.render_enemies()
            self.calculate_counters()

    def remove_enemy(self, hero_slug):
        if hero_slug in self.selected_enemies:
            self.selected_enemies.remove(hero_slug)
            self.render_enemies()
            self.calculate_counters()

    def clear_enemies(self):
        self.selected_enemies = []
        self.render_enemies()
        self.calculate_counters()

    def create_placeholder_icon_label(self, hero_slug, width, height):
        initial = hero_slug[0].upper() if hero_slug else "?"
        lbl = QLabel(initial)
        lbl.setAlignment(Qt.AlignCenter)
        font_size = int(height * 0.7)
        lbl.setStyleSheet(f"""
            color: {COLOR_TEXT_WHITE};
            background-color: {COLOR_DANGER_RED};
            border: 1px dashed {COLOR_TEXT_WHITE};
            border-radius: 4px;
            font-size: {font_size}px;
            font-weight: bold;
        """)
        lbl.setFixedSize(QSize(width, height))
        return lbl

    def render_enemies(self):
        for i in reversed(range(self.enemies_list_layout.count())):
            item = self.enemies_list_layout.itemAt(i)
            if item.widget() and item.widget().objectName() != "":
                item.widget().deleteLater()
            elif item.widget() is None:
                self.enemies_list_layout.removeItem(item)

        self.search_block.update_status(len(self.selected_enemies))

        for hero in self.selected_enemies:
            hero_name = hero.replace("-", " ").title()

            card = QFrame()
            card.setObjectName("EnemyCard")
            card.setMinimumHeight(30)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(5, 3, 0, 3)
            card_layout.setSpacing(6)

            pixmap = get_hero_icon_from_local(hero, ICON_WIDTH_SMALL, ICON_HEIGHT_SMALL)
            if pixmap:
                icon_lbl = QLabel()
                icon_lbl.setPixmap(pixmap)
                icon_lbl.setFixedSize(QSize(ICON_WIDTH_SMALL, ICON_HEIGHT_SMALL))
            else:
                icon_lbl = self.create_placeholder_icon_label(hero, ICON_WIDTH_SMALL, ICON_HEIGHT_SMALL)

            card_layout.addWidget(icon_lbl)

            lbl = QLabel(hero_name)
            card_layout.addWidget(lbl)

            del_btn = QPushButton("\u00D7")
            del_btn.setObjectName("RemoveButton")
            del_btn.setFixedSize(25, 25)
            del_btn.clicked.connect(lambda _, h=hero: self.remove_enemy(h))
            card_layout.addWidget(del_btn)

            self.enemies_list_layout.insertWidget(self.enemies_list_layout.count() - 1, card)

        if self.enemies_list_layout.itemAt(self.enemies_list_layout.count() - 1) is None:
            self.enemies_list_layout.addStretch(1)

    def calculate_counters(self):
        self.animation_timer.stop()
        self.animated_results = []
        while self.results_list_layout.count() > 0:
            item = self.results_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            del item

        if not self.selected_enemies:
            placeholder_lbl = QLabel(">>> ДОБАВЬТЕ ГЕРОЕВ ДЛЯ АНАЛИЗА <<<")
            placeholder_lbl.setStyleSheet(f"color: {COLOR_TEXT_GRAY}; padding: 50px 0; font-size: 16px;")
            placeholder_lbl.setAlignment(Qt.AlignCenter)
            self.results_list_layout.addWidget(placeholder_lbl)
            self.results_list_layout.addStretch(1)
            return

        scores = {}
        is_anti_mage_enemy = AM_SLUG in self.selected_enemies
        enemies_for_general_calc = [e for e in self.selected_enemies if e != AM_SLUG]

        for candidate_slug in self.all_heroes:
            if candidate_slug in self.selected_enemies:
                continue

            total_advantage = 0
            if is_anti_mage_enemy:
                total_advantage += float(self.am_counters_data.get(candidate_slug, 0.0) or 0.0)

            for enemy_slug in enemies_for_general_calc:
                matchups = self.hero_data.get(candidate_slug, {})
                normalized_enemy_key = normalize_hero_name(enemy_slug)
                total_advantage += float(matchups.get(normalized_enemy_key, 0.0) or 0.0)

            scores[candidate_slug] = round(total_advantage, 2)

        non_zero_scores = {hero: score for hero, score in scores.items() if score != 0.0}

        if not non_zero_scores:
            placeholder_lbl = QLabel(">>> НЕТ РЕКОМЕНДАЦИЙ <<<")
            placeholder_lbl.setStyleSheet(f"color: {COLOR_ACCENT}; padding: 50px 0; font-size: 16px;")
            placeholder_lbl.setAlignment(Qt.AlignCenter)
            self.results_list_layout.addWidget(placeholder_lbl)
            self.results_list_layout.addStretch(1)
            return

        best_heroes = sorted(non_zero_scores.items(), key=lambda x: x[1], reverse=True)[:20]

        for rank, (hero, score) in enumerate(best_heroes, 1):
            row = self._create_result_row_widget(rank, hero, score)
            self.results_list_layout.addWidget(row)
            self.animated_results.append(row)

        self.animation_timer.start(50)
        self.results_list_layout.addStretch(1)

    def _animate_next_result_row(self):
        if self.animated_results:
            row = self.animated_results.pop(0)
            row.start_animation(75)
        else:
            self.animation_timer.stop()

    def _animate_next_picker_row(self):
        if self.picker_animated_results:
            row = self.picker_animated_results.pop(0)
            row.start_animation(75)
        else:
            self.picker_animation_timer.stop()

    def _create_result_row_widget(self, rank, hero, score):
        row = ResultRow()
        row.setProperty("class", "ResultRowOdd" if rank % 2 != 0 else "ResultRowEven")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(15, 10, 15, 10)
        row_layout.setSpacing(10)

        rank_color = COLOR_ACCENT if rank <= 3 else COLOR_TEXT_GRAY
        rank_lbl = QLabel(f"{rank:02d}.")
        rank_lbl.setFixedWidth(35)
        rank_lbl.setStyleSheet(f"color: {rank_color}; font-weight: bold; font-size: 15px;")
        row_layout.addWidget(rank_lbl)

        pixmap = get_hero_icon_from_local(hero, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)
        if pixmap:
            hero_icon_lbl = QLabel()
            hero_icon_lbl.setPixmap(pixmap)
            hero_icon_lbl.setFixedWidth(ICON_WIDTH_LARGE)
        else:
            hero_icon_lbl = self.create_placeholder_icon_label(hero, ICON_WIDTH_LARGE, ICON_HEIGHT_LARGE)

        row_layout.addWidget(hero_icon_lbl)

        display_name = hero.replace("-", " ").title()
        name_lbl = QLabel(display_name)
        name_lbl.setFont(QFont(FONT_FAMILY_MAIN, 14))
        name_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        row_layout.addWidget(name_lbl)

        row_layout.addStretch(1)

        score_text = f"{score:+.2f}"
        color = COLOR_SUCCESS_GREEN if score > 0 else COLOR_DANGER_RED

        score_lbl = QLabel(score_text)
        score_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        score_lbl.setFixedWidth(80)
        score_lbl.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: bold;")
        row_layout.addWidget(score_lbl)

        return row

    def _generate_stylesheet(self):
        bg_image_path = resource_path(BACKGROUND_IMAGE_FILE)
        return f"""
            QMainWindow {{
                background-color: #000000;
                background-image: url({bg_image_path});
                background-repeat: no-repeat;
                background-position: center;
                background-attachment: fixed;
                background-size: cover;
                border: none;
            }}
            QWidget {{
                background-color: transparent;
                color: {COLOR_TEXT_WHITE};
                font-family: {FONT_FAMILY_MAIN}; 
                font-size: 14px;
            }}

            *:focus {{
                outline: 0px;
                border: none;
            }}

            QFrame#HeaderFrame {{
                background-color: {COLOR_GLASS_DARK};
                padding: 20px 0px; 
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 0;
            }}

            QPushButton#HamburgerButton {{
                background-color: transparent;
                border: none;
                color: {COLOR_TEXT_GRAY};
                font-size: 28px;
                font-weight: normal;
                padding: 0;
                margin: 0;
            }}
            QPushButton#HamburgerButton:hover {{
                color: {COLOR_TEXT_WHITE};
            }}

            QPushButton#SidebarButton {{
                background-color: {COLOR_GLASS_DARK};
                color: {COLOR_TEXT_GRAY}; 
                font-size: 14px; 
                font-weight: bold;
                text-align: center;
                padding: 16px 18px;
                margin: 5px 5px;
                border-radius: 10px;
                border: 2px solid #4a1515;
                min-height: 20px;
            }}
            QPushButton#SidebarButton:hover {{
                background-color: rgba(220, 38, 38, 0.25);
                border-color: {COLOR_ACCENT};
                color: {COLOR_TEXT_WHITE};
            }}
            QPushButton#SidebarButton:pressed {{
                background-color: rgba(220, 38, 38, 0.4);
                border-color: {COLOR_ACCENT};
                color: {COLOR_TEXT_WHITE};
            }}

            QLabel#LogoText {{
                font-size: 24px; 
                font-weight: bold; 
                color: {COLOR_TEXT_WHITE}; 
                font-family: {FONT_FAMILY_LOGO}; 
                letter-spacing: 1px;
                margin-left: 10px;
            }}

            QLabel#TitleLabel {{
                font-size: 18px; 
                font-weight: bold;
                color: {COLOR_TEXT_WHITE}; 
                padding-bottom: 8px;
                letter-spacing: 1px;
            }}

            QFrame.Card {{
                background-color: {COLOR_TRANSPARENT_CARD};
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: {BORDER_RADIUS};
            }}

            QLineEdit {{
                background-color: {COLOR_GLASS_DARK}; 
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 12px;
                font-size: 15px;
                color: {COLOR_TEXT_WHITE};
                outline: none;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLOR_ACCENT};
                background-color: {COLOR_GLASS_MEDIUM};
            }}

            QListWidget {{
                background-color: {COLOR_GLASS_MEDIUM};
                border: none;
                border-radius: 4px;
                color: {COLOR_TEXT_WHITE};
                font-size: 13px;
                padding-bottom: 2px;
                outline: 0; 
            }}
            QListWidget::item:hover {{
                background-color: {COLOR_HOVER};
            }}
            QListWidget::item:selected {{
                background-color: rgba(60, 60, 60, 0.8);
                color: {COLOR_ACCENT};
            }}

            QPushButton {{
                background-color: {COLOR_ACCENT}; 
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                color: {COLOR_TEXT_WHITE};
                font-weight: bold;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: #FF5252;
            }}
            QPushButton:pressed {{
                background-color: {COLOR_ACCENT_DARK};
            }}

            QFrame#EnemyCard {{
                background-color: {COLOR_GLASS_LIGHT}; 
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 0;
            }}

            QPushButton#RemoveButton {{
                background-color: transparent;
                border: none;
                color: {COLOR_TEXT_GRAY};
                font-weight: bold;
                padding: 0 5px;
                font-size: 20px; 
                line-height: 1; 
                text-align: center;
                outline: none;
            }}
            QPushButton#RemoveButton:hover {{
                color: {COLOR_ACCENT};
            }}

            QPushButton#WindowControlButton {{
                background-color: transparent;
                border: none;
                color: {COLOR_TEXT_WHITE};
                font-weight: bold;
                font-size: 18px; 
                padding: 5px 10px;
                min-width: 40px;
                border-radius: 0;
                outline: none;
            }}
            QPushButton#WindowControlButton:hover {{
                background-color: rgba(85, 85, 85, 0.7);
            }}


            QPushButton#CloseWindowButton {{
                background-color: transparent;
                border: none;
                color: {COLOR_TEXT_WHITE};
                font-weight: bold;
                font-size: 24px; 
                padding: 0 10px; 
                min-width: 40px;
                border-radius: 0;
                outline: none;
            }}
            QPushButton#CloseWindowButton:hover {{
                background-color: {COLOR_ACCENT}; 
                color: {COLOR_TEXT_WHITE};
            }}

            QPushButton#RefreshCacheButton {{
                background-color: rgba(220, 38, 38, 0.25);
                border: 1px solid {COLOR_ACCENT};
                border-radius: 8px;
                color: {COLOR_TEXT_WHITE};
                font-size: 12px;
                padding: 8px 16px;
            }}
            QPushButton#RefreshCacheButton:hover {{
                background-color: rgba(220, 38, 38, 0.45);
                color: {COLOR_TEXT_WHITE};
            }}
            QPushButton#RefreshCacheButton:disabled {{
                background-color: rgba(100, 100, 100, 0.2);
                border-color: {COLOR_TEXT_GRAY};
                color: {COLOR_TEXT_GRAY};
            }}

            QScrollArea {{
                border: none;
                border-radius: 8px;
                background-color: transparent; 
            }}

            QFrame.ResultRowOdd {{
                background-color: {COLOR_GLASS_LIGHT}; 
                border-radius: 8px;
                margin: 4px 0;
                padding: 10px 0px;
                border: 1px solid rgba(255, 255, 255, 0.03);
            }}
            QFrame.ResultRowOdd:hover {{
                background-color: {COLOR_HOVER};
                border: 1px solid rgba(220, 38, 38, 0.3);
            }}
            QFrame.ResultRowEven {{
                background-color: {COLOR_TRANSPARENT_CARD};
                border-radius: 8px;
                margin: 4px 0;
                padding: 10px 0px;
                border: 1px solid rgba(255, 255, 255, 0.03);
            }}
            QFrame.ResultRowEven:hover {{
                background-color: {COLOR_HOVER};
                border: 1px solid rgba(220, 38, 38, 0.3);
            }}

            QScrollBar:vertical {{
                border: none;
                background: transparent; 
                width: 8px;
                margin: 0px 0 0px 0;
            }}
            QScrollBar::handle:vertical {{
                background-color: rgba(68, 68, 68, 0.8); 
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {COLOR_ACCENT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
                height: 0px;
            }}
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {{
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QSplitter::handle {{
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 3px;
            }}
            QSplitter::handle:hover {{
                background-color: rgba(220, 38, 38, 0.35);
            }}
            QSplitter::handle:vertical {{
                margin: 6px 0;
                height: 6px;
            }}
            QSplitter::handle:horizontal {{
                margin: 0 6px;
                width: 6px;
            }}
            QSizeGrip {{
                width: 16px;
                height: 16px;
                background: transparent;
            }}
        """


    def closeEvent(self, event):
        """Очистка ресурсов"""
        if hasattr(self, 'auto_scan_timer'):
            self.auto_scan_timer.stop()
        if hasattr(self, 'pick_monitor_timer'):
            self.pick_monitor_timer.stop()
        if hasattr(self, 'animation_timer'):
            self.animation_timer.stop()
        if hasattr(self, 'picker_animation_timer'):
            self.picker_animation_timer.stop()
        if hasattr(self, 'pick_detector'):
            self.pick_detector.stop_monitoring()
        if hasattr(self, 'cv_scanner'):
            self.cv_scanner.auto_scan_enabled = False
        QApplication.quit()
        event.accept()

if __name__ == "__main__":
    if sys.platform == 'win32':
        try:
            myappid = f'metamind.dota2.counterpick.v{APP_VERSION}'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QApplication(sys.argv)

    icon_path = resource_path("app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # === ЗАПУСК GSI СЕРВЕРА В ФОНЕ ===
    gsi_thread = threading.Thread(target=start_gsi_server, daemon=True)
    gsi_thread.start()
    print("[MAIN] ✅ GSI сервер запущен в фоне")

    main_window = None


    def on_splash_loaded(opendota_data):
        global main_window
        main_window = MainWindow()
        if opendota_data:
            main_window.opendota_cache = opendota_data
        main_window.show()


    splash = SplashScreen(on_splash_loaded)
    splash.start()

    sys.exit(app.exec())
