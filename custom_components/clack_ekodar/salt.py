"""Salt-level accounting model for the Clack EM.S valve.

Pure Python (no HA imports) so it is unit-testable without Home Assistant.

Model: salt in the brine tank is tracked in kilograms. A human presses the
"Salt added" button when a bag is dumped in -> level += bag_kg (clamped to the
tank capacity). Every completed regeneration consumes kg_per_regen, taken from
either an explicit config field or bag_kg / regens_per_bag. State survives
restarts via a JSON dict (to_dict/load_state) persisted by the integration
under .storage/.

Rules (task t_6718b8d8):
  * level is None until the first bag is added or state is restored;
  * level never goes below 0 nor above tank_kg;
  * regeneration subtracts only when a level is known;
  * division by zero is guarded (invalid config -> kg_per_regen None);
  * warning thresholds (salt_warn_kg / salt_warn_regens) live in the config.

Warning layer (task t_3dc7971b): SaltModel.status() folds the model into a
human-facing readiness kind — ok | low | no_data | incomplete — plus the
recommended number of bags; format_status_message() renders the localized
"what to do" text. `incomplete` is the *deferred* warning: level is tracked
but per-regen consumption is unknown, so the notification asks to complete
the settings instead of crying wolf.
"""
from __future__ import annotations

import math
import time

MAX_EVENTS = 50

# Human-facing readiness kinds (t_3dc7971b warning layer). Order of precedence
# in SaltModel.status(): no_data > low > incomplete > ok.
STATUS_KINDS = ("ok", "low", "no_data", "incomplete")


class SaltConfig:
    """Validated numeric settings for salt accounting."""

    def __init__(self, bag_kg: float = 25.0, regens_per_bag: float = 10.0,
                 kg_per_regen: float = 0.0, tank_kg: float = 60.0,
                 warn_kg: float = 5.0, warn_regens: float = 2.0) -> None:
        self.bag_kg = float(bag_kg) if bag_kg and bag_kg > 0 else 0.0
        self.regens_per_bag = (float(regens_per_bag) if regens_per_bag
                                and regens_per_bag > 0 else 0.0)
        self.kg_per_regen_cfg = (float(kg_per_regen) if kg_per_regen
                                 and kg_per_regen > 0 else 0.0)
        self.tank_kg = float(tank_kg) if tank_kg and tank_kg > 0 else 0.0
        self.warn_kg = float(warn_kg) if warn_kg and warn_kg > 0 else 0.0
        self.warn_regens = (float(warn_regens) if warn_regens
                            and warn_regens >= 0 else 0.0)

    @classmethod
    def from_mapping(cls, d: dict | None) -> "SaltConfig":
        d = d or {}
        return cls(
            bag_kg=d.get("salt_bag_kg", 25.0),
            regens_per_bag=d.get("salt_regens_per_bag", 10.0),
            kg_per_regen=d.get("salt_kg_per_regen", 0.0),
            tank_kg=d.get("salt_tank_kg", 60.0),
            warn_kg=d.get("salt_warn_kg", 5.0),
            warn_regens=d.get("salt_warn_regens", 2.0),
        )

    def kg_per_regen(self) -> float | None:
        """Explicit kg_per_regen wins; else bag/regens; invalid -> None."""
        if self.kg_per_regen_cfg > 0:
            return self.kg_per_regen_cfg
        if self.bag_kg > 0 and self.regens_per_bag > 0:
            return self.bag_kg / self.regens_per_bag
        return None


class SaltModel:
    """Kg-level state + event log for one valve."""

    def __init__(self, config: SaltConfig | None = None) -> None:
        self.config = config or SaltConfig()
        self.level_kg: float | None = None
        self.last_added: dict | None = None  # {ts, bags, kg, level_after}
        self.events: list[dict] = []
        self.regens_tracked: int = 0  # subtractions applied since restore

    # ----- actions -----

    def add_bags(self, bags: float = 1, ts: float | None = None) -> dict:
        """'Добавлена соль': raise level by bags * bag_kg, clamp to tank."""
        if bags <= 0 or self.config.bag_kg <= 0:
            return {}
        now = time.time() if ts is None else float(ts)
        kg = bags * self.config.bag_kg
        base = 0.0 if self.level_kg is None else self.level_kg
        new = base + kg
        if self.config.tank_kg > 0:
            new = min(new, self.config.tank_kg)
        self.level_kg = round(new, 2)
        self.last_added = {"ts": now, "bags": bags, "kg": round(kg, 2),
                           "level_after": self.level_kg}
        self._event("salt_added", now, kg=round(kg, 2),
                    level=self.level_kg, bags=bags)
        return self.last_added

    def on_regeneration(self, ts: float | None = None) -> bool:
        """Subtract one regeneration's consumption. True if applied."""
        if self.level_kg is None:
            return False  # unknown level: nothing to subtract
        per = self.config.kg_per_regen()
        if per is None:
            return False  # incomplete data; leave level untouched
        now = time.time() if ts is None else float(ts)
        before = self.level_kg
        new = max(0.0, before - per)  # never negative
        if self.config.tank_kg > 0:
            new = min(new, self.config.tank_kg)
        self.level_kg = round(new, 2)
        self.regens_tracked += 1
        self._event("regen_consumed", now, kg=round(per, 3),
                    level=self.level_kg,
                    zeroed=before > 0 and self.level_kg == 0.0)
        return True

    # ----- derived -----

    def regen_remaining(self) -> float | None:
        """How many full regenerations the remaining salt can serve."""
        per = self.config.kg_per_regen()
        if self.level_kg is None or per is None or per <= 0:
            return None
        return int(self.level_kg // per)

    def percent(self) -> float | None:
        if self.level_kg is None or self.config.tank_kg <= 0:
            return None
        return round(100.0 * self.level_kg / self.config.tank_kg, 1)

    @property
    def is_low(self) -> bool | None:
        """None = unknown level (don't fire a false warning)."""
        if self.level_kg is None:
            return None
        if self.config.warn_kg > 0 and self.level_kg < self.config.warn_kg:
            return True
        rem = self.regen_remaining()
        if rem is not None and self.config.warn_regens > 0:
            return rem < self.config.warn_regens
        return False

    # ----- human-facing warning layer (t_3dc7971b) -----

    def status(self) -> dict:
        """Fold the model into one readiness dict for UI/notifications.

        kind precedence:
          no_data    — level unknown (salt never added, nothing restored);
          low        — is_low says so (kg floor or regen threshold crossed);
          incomplete — level known but kg_per_regen unknown: regeneration
                       data incomplete, so the regen-count warning is
                       *deferred* until the config is fixed;
          ok         — tracked level comfortably above both thresholds.
        bags_recommended — how many whole bags to top the warning buffer back
        up (>=1 whenever a refill is advised, 0 on ok, None if bag size is
        unknown).
        """
        per = self.config.kg_per_regen()
        rem = self.regen_remaining()
        low = self.is_low
        if self.level_kg is None:
            kind = "no_data"
        elif low:
            kind = "low"
        elif per is None or rem is None:
            kind = "incomplete"
        else:
            kind = "ok"
        return {
            "kind": kind,
            "level_kg": self.level_kg,
            "percent": self.percent(),
            "regen_remaining": rem,
            "kg_per_regen": round(per, 3) if per else None,
            "bags_recommended": self._bags_recommended(kind),
        }

    def _bags_recommended(self, kind: str) -> int | None:
        cfg = self.config
        if kind == "ok":
            return 0
        if cfg.bag_kg <= 0:
            return None
        if kind in ("no_data", "incomplete"):
            return 1  # start/correct bookkeeping with a standard bag
        per = cfg.kg_per_regen()
        target = None
        if per is not None and cfg.warn_regens > 0:
            target = per * (cfg.warn_regens + 1)
        if cfg.warn_kg > 0:
            target = cfg.warn_kg if target is None else max(target, cfg.warn_kg)
        if target is None:
            return 1
        need = max(0.0, target - (self.level_kg or 0.0))
        if cfg.tank_kg > 0 and self.level_kg is not None:
            need = min(need, max(0.0, cfg.tank_kg - self.level_kg))
        return max(1, math.ceil(round(need / cfg.bag_kg, 6)))


    def _event(self, kind: str, ts: float, **extra) -> None:
        self.events.append({"kind": kind, "ts": ts, **extra})
        if len(self.events) > MAX_EVENTS:
            del self.events[:-MAX_EVENTS]

    # ----- persistence -----

    def to_dict(self) -> dict:
        return {
            "level_kg": self.level_kg,
            "last_added": self.last_added,
            "events": self.events[-MAX_EVENTS:],
            "regen_consumed": self.regens_tracked,
        }

    def load_state(self, data: dict | None) -> None:
        if not isinstance(data, dict):
            return
        level = data.get("level_kg")
        if isinstance(level, (int, float)) and level >= 0:
            self.level_kg = float(level)
        last = data.get("last_added")
        if isinstance(last, dict) and "ts" in last:
            self.last_added = last
        events = data.get("events")
        if isinstance(events, list):
            self.events = [e for e in events
                           if isinstance(e, dict)][-MAX_EVENTS:]
        consumed = data.get("regen_consumed")
        if isinstance(consumed, int) and consumed >= 0:
            self.regens_tracked = consumed


# ---------------------------------------------------------------------------
# Warning-layer message rendering (t_3dc7971b). Pure string logic so it is
# unit-testable; the sensor/notification layers only pick a language.

_RU_BAG = ("мешок", "мешка", "мешков")
_RU_REGEN = ("промывку", "промывки", "промывок")


def _plural_ru(n: int, forms: tuple[str, str, str]) -> str:
    if n % 100 in range(11, 15):
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    if last in range(2, 5):
        return forms[1]
    return forms[2]


def _fmt_num(v) -> str:
    if v is None:
        return "?"
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:g}"


def format_status_message(status: dict, lang: str = "ru") -> str:
    """One-line human recommendation derived from SaltModel.status()."""
    kind = status.get("kind", "ok")
    level = status.get("level_kg")
    rem = status.get("regen_remaining")
    bags = status.get("bags_recommended")
    ru = lang.startswith("ru")

    if kind == "ok":
        if ru:
            txt = f"Соль в норме: {_fmt_num(level)} кг"
            if rem is not None:
                txt += f" (~{_fmt_num(rem)} {_plural_ru(int(rem), _RU_REGEN)})"
            return txt + "."
        txt = f"Salt level OK: {_fmt_num(level)} kg"
        if rem is not None:
            txt += f" (~{_fmt_num(rem)} regens)"
        return txt + "."

    if kind == "low":
        bags_txt = (f"{_fmt_num(bags)} "
                    + (_plural_ru(int(bags), _RU_BAG) if ru
                       else ("bag" if int(bags) == 1 else "bags"))) \
            if bags else ("соль" if ru else "salt")
        if ru:
            txt = f"Мало соли: осталось {_fmt_num(level)} кг"
            if rem is not None:
                txt += f", хватит на {_fmt_num(rem)} {_plural_ru(int(rem), _RU_REGEN)}"
            return txt + f". Досыпьте {bags_txt} и нажмите «Добавлена соль»."
        txt = f"Low salt: {_fmt_num(level)} kg left"
        if rem is not None:
            unit = "regen" if int(rem) == 1 else "regens"
            txt += f", ~{_fmt_num(rem)} {unit} remaining"
        return txt + f". Add {bags_txt} and press \"Salt added\"."

    if kind == "no_data":
        if ru:
            return ("Уровень соли неизвестен — учёт ещё не начат. "
                    "Добавьте соль и нажмите «Добавлена соль», чтобы "
                    "интеграция начала считать расход.")
        return ("Salt level unknown — tracking has not started. Add salt "
                "and press \"Salt added\" so the integration can track "
                "consumption.")

    # incomplete: level tracked but per-regeneration data unknown → deferred
    if ru:
        return (f"Данные о расходе соли неполные: уровень {_fmt_num(level)} кг "
                "известен, но сколько соли уходит на промывку — нет. "
                "Укажите «промывок на мешок» или «кг на промывку» в "
                "настройках интеграции; предупреждение по остатку отложено.")
    return (f"Salt usage data incomplete: level is {_fmt_num(level)} kg but "
            "kg per regeneration is unknown. Set \"regenerations per bag\" "
            "or \"kg per regen\" in the integration options; the low-salt "
            "warning is deferred until then.")


class RegenTracker:
    """Detect *completed* regeneration sessions from MQTT traffic.

    The valve streams command=110 every ~30 s while regenerating (and 100
    status frames keep flowing in parallel), so a session ends only when 110
    has been silent for END_GAP_S. Sessions with fewer than MIN_MSGS frames
    are treated as incomplete data -> not counted (warning task defers them).
    """

    END_GAP_S = 120.0
    MIN_MSGS = 2

    def __init__(self) -> None:
        self.session_open = False
        self.msg_count = 0
        self.last_seen = 0.0
        self.session_started = 0.0

    def on_message(self, code: int, ts: float) -> bool:
        """Feed one MQTT command code; True when a full regen just ended."""
        if code == 110:
            if not self.session_open:
                self.session_open = True
                self.msg_count = 0
                self.session_started = ts
            self.msg_count += 1
            self.last_seen = ts
            return False
        if code == 100:
            if self.session_open and (ts - self.last_seen) > self.END_GAP_S:
                full = self.msg_count >= self.MIN_MSGS
                self.session_open = False
                self.msg_count = 0
                return full
        return False
