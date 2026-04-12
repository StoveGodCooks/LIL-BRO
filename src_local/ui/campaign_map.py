"""Campaign map modal -- `/campaign` opens a two-column area/quest browser.

Layout (mirrors ProjectSwitcherScreen's two-column pattern, but with
two ListViews side-by-side so the user can see all areas at once and
page the quest list on the right as they move through them):

    +---------------- THE CODELANDS ----------------+
    | X The Cave          | Done cave_01 Baby Steps  |
    | Locked Loop Labyrinth| >  cave_02 Walk First   |
    | Locked OOP Citadel   |    cave_03 Name Things  |
    | Locked Async Shores  |    ...                   |
    | Locked Error Marsh   | X  cave_boss Cave Fear   |
    +------------------------------------------------+
    |  Up/Down navigate  Tab switch  Enter select  Esc|
    +------------------------------------------------+

Icon rules:

    Area:   Done    fully complete
            Active  unlocked + in progress
            Locked  locked (prior area < 80% done)

    Quest:  Done     completed
            Active   currently active
            Boss     boss quest (unfinished)
            Locked   area is locked
                     (blank) unfinished normal quest

The screen takes three plain arguments -- a ``World``, a
``CampaignState``, and an ``on_select`` callback that fires with the
chosen ``Quest``. The callback model (not event bubbling) mirrors
ProjectSwitcherScreen so the app can push this modal from anywhere
without wiring new message types.
"""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

from src_local.quests.models import Area, Quest, World
from src_local.quests.state import CampaignState


# Icons are kept as module constants so tests can assert on them
# without hardcoding magic strings in two places.
ICON_AREA_DONE = "✅"
ICON_AREA_ACTIVE = "⚔"
ICON_AREA_LOCKED = "🔒"

ICON_QUEST_DONE = "✅"
ICON_QUEST_ACTIVE = "▶"
ICON_QUEST_BOSS = "⚔"
ICON_QUEST_LOCKED = "🔒"
ICON_QUEST_TODO = " "


# -------------------------------------------------------------------
# Pure helpers (testable without a running App)
# -------------------------------------------------------------------

def area_icon(area: Area, state: CampaignState, world: World) -> str:
    """Return the prefix icon for an area row."""
    if not state.is_area_unlocked(area.id, world):
        return ICON_AREA_LOCKED
    if state.area_completion_ratio(area.id, world) >= 1.0:
        return ICON_AREA_DONE
    return ICON_AREA_ACTIVE


def quest_icon(
    quest_id: str,
    is_boss: bool,
    area: Area,
    state: CampaignState,
    world: World,
) -> str:
    """Return the prefix icon for a single quest row."""
    if not state.is_area_unlocked(area.id, world):
        return ICON_QUEST_LOCKED
    if state.is_quest_done(quest_id):
        return ICON_QUEST_DONE
    if state.current_quest_id == quest_id:
        return ICON_QUEST_ACTIVE
    if is_boss:
        return ICON_QUEST_BOSS
    return ICON_QUEST_TODO


def area_label(area: Area, state: CampaignState, world: World) -> str:
    icon = area_icon(area, state, world)
    pct = int(round(state.area_completion_ratio(area.id, world) * 100))
    return f"{icon}  {area.name}  ({pct}%)"


def quest_label(
    quest_id: str,
    is_boss: bool,
    area: Area,
    state: CampaignState,
    world: World,
    lookup_title: Callable[[str], str] | None = None,
) -> str:
    icon = quest_icon(quest_id, is_boss, area, state, world)
    title = lookup_title(quest_id) if lookup_title is not None else quest_id
    suffix = "  (boss)" if is_boss else ""
    return f"{icon}  {quest_id}  --  {title}{suffix}"


# -------------------------------------------------------------------
# Modal screen
# -------------------------------------------------------------------

class CampaignMapScreen(ModalScreen):
    """Floating campaign map -- `/campaign` or action_show_campaign_map."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("tab", "toggle_column", "Switch column", show=False),
    ]

    def __init__(
        self,
        world: World,
        state: CampaignState,
        on_select: Callable[[Quest], None],
        quest_lookup: Callable[[str], "Quest | None"] | None = None,
    ) -> None:
        super().__init__()
        self._world = world
        self._state = state
        self._on_select = on_select
        self._quest_lookup = quest_lookup

    # -----------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="campaign-container"):
            yield Static("-- THE CODELANDS --", id="campaign-title")
            with Horizontal(id="campaign-columns"):
                yield ListView(*self._build_area_items(), id="area-list")
                yield ListView(*self._build_quest_items(0), id="quest-list")
            yield Static(
                "Up/Down navigate  Tab switch column  Enter select  Esc close",
                id="campaign-footer",
            )

    # -----------------------------------------------------------------
    # Row builders
    # -----------------------------------------------------------------

    def _build_area_items(self) -> list[ListItem]:
        items: list[ListItem] = []
        for area in self._world.areas:
            label = area_label(area, self._state, self._world)
            items.append(ListItem(Static(label)))
        return items

    def _build_quest_items(self, area_index: int) -> list[ListItem]:
        if not self._world.areas or area_index >= len(self._world.areas):
            return []
        area = self._world.areas[area_index]
        items: list[ListItem] = []
        for qid in area.quest_ids:
            label = quest_label(
                qid,
                is_boss=False,
                area=area,
                state=self._state,
                world=self._world,
                lookup_title=self._lookup_title,
            )
            items.append(ListItem(Static(label)))
        if area.boss_quest_id:
            label = quest_label(
                area.boss_quest_id,
                is_boss=True,
                area=area,
                state=self._state,
                world=self._world,
                lookup_title=self._lookup_title,
            )
            items.append(ListItem(Static(label)))
        return items

    def _lookup_title(self, quest_id: str) -> str:
        if self._quest_lookup is None:
            return quest_id
        q = self._quest_lookup(quest_id)
        return q.title if q is not None else quest_id

    # -----------------------------------------------------------------
    # Interaction
    # -----------------------------------------------------------------

    def on_mount(self) -> None:
        if self._world.areas:
            try:
                self.query_one("#area-list", ListView).focus()
            except Exception:  # noqa: BLE001
                pass

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """When the user moves through the area column, rebuild the
        quest list on the right to match."""
        if event.list_view.id != "area-list":
            return
        idx = event.list_view.index or 0
        try:
            quest_list = self.query_one("#quest-list", ListView)
        except Exception:  # noqa: BLE001
            return
        quest_list.clear()
        for item in self._build_quest_items(idx):
            quest_list.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter pressed on either column.

        On the area column: focus the quest column for that area.
        On the quest column: dismiss + fire ``on_select`` if the area
        is unlocked and a quest lookup is available.
        """
        lv = event.list_view
        if lv.id == "area-list":
            try:
                quest_list = self.query_one("#quest-list", ListView)
                quest_list.focus()
            except Exception:  # noqa: BLE001
                pass
            return
        if lv.id != "quest-list":
            return
        area_idx = self._active_area_index()
        if area_idx is None or area_idx >= len(self._world.areas):
            return
        area = self._world.areas[area_idx]
        if not self._state.is_area_unlocked(area.id, self._world):
            return
        quest_idx = lv.index
        if quest_idx is None:
            return
        ids = list(area.quest_ids)
        if area.boss_quest_id:
            ids.append(area.boss_quest_id)
        if quest_idx >= len(ids):
            return
        qid = ids[quest_idx]
        if self._quest_lookup is None:
            return
        quest = self._quest_lookup(qid)
        if quest is None:
            return
        self.dismiss(None)
        try:
            self._on_select(quest)
        except Exception:  # noqa: BLE001
            pass

    def action_toggle_column(self) -> None:
        """Tab: swap focus between the area list and the quest list."""
        try:
            area_lv = self.query_one("#area-list", ListView)
            quest_lv = self.query_one("#quest-list", ListView)
        except Exception:  # noqa: BLE001
            return
        if self.focused is area_lv:
            quest_lv.focus()
        else:
            area_lv.focus()

    def action_close(self) -> None:
        self.dismiss(None)

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _active_area_index(self) -> int | None:
        try:
            lv = self.query_one("#area-list", ListView)
        except Exception:  # noqa: BLE001
            return None
        return lv.index
