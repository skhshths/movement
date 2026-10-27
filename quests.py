"""
Story, characters and deliveries.

The Static, a storm of noise, has knocked out every beacon in the Reach, so
the towns can no longer signal each other. Only couriers connect them. Ren,
a retired courier in Lowmarket, sends you out to carry the parts needed to
relight the great beacon at Skyhold. Each stop teaches new tricks.

Every town also has a Dispatcher handing out delivery jobs to other towns,
paid in coins, with a bonus for beating the par time.
"""
import math
import random

# id -> name, town, x offset in the town, body colour, idle lines
NPCS = {
    "ren": dict(name="Ren", town="lowmarket", dx=-250, color=(240, 196, 120),
                idle=["Every courier falls. The good ones fall forward.",
                      "Keep moving. Standing still is how the Static gets you."]),
    "mara": dict(name="Mara", town="lowmarket", dx=780, color=(255, 120, 150),
                 idle=["Spice, cloth, rope, rumours. I sell it all.",
                       "Ren used to be the fastest thing in the Reach."]),
    "pip": dict(name="Pip", town="lowmarket", dx=330, color=(150, 230, 140),
                idle=["When I grow up I'm gonna wavedash everywhere!",
                      "Hold S while you run. Wheee!"]),
    "brask": dict(name="Brask", town="cinder", dx=150, color=(255, 140, 70),
                  idle=["Hot work, forging. Hotter running.",
                        "Don't touch the coils. Trust me."]),
    "soot": dict(name="Soot", town="cinder", dx=-420, color=(150, 120, 120),
                 idle=["The valley walls are tall. Kick off them.",
                       "Lost my eyebrows to the forge. Worth it."]),
    "isolde": dict(name="Isolde", town="mistral", dx=250, color=(150, 220, 255),
                   idle=["The wind up here never stops talking.",
                         "Fall off the Spire and it's a long walk back."]),
    "tamsin": dict(name="Tamsin", town="verdant", dx=-100, color=(140, 255, 130),
                   idle=["Mind the edges. The Shelf doesn't have railings.",
                         "Everything grows up here. Even couriers."]),
    "fennel": dict(name="Fennel", town="verdant", dx=520, color=(220, 240, 120),
                   idle=["Skim the Shelf's belly at speed. It's a rush.",
                         "I planted a tree once. It floated away."]),
    "orrin": dict(name="Orrin", town="glasswater", dx=200, color=(190, 160, 255),
                  idle=["Glass remembers every hand that shaped it.",
                        "Bunny hop the flats. Never touch the ground for long."]),
    "keeper": dict(name="The Keeper", town="skyhold", dx=0, color=(255, 236, 160),
                   idle=["The beacon burns. You did that.",
                         "Even up here, you can hear the towns now."]),
}
TOWN_IDS = ["lowmarket", "cinder", "mistral", "verdant", "glasswater", "skyhold"]
for _tid in TOWN_IDS:
    NPCS[f"{_tid}_disp"] = dict(name="Dispatcher", town=_tid, dx=-640,
                                color=(255, 214, 90),
                                idle=["Jobs come in all day."])

# each step: who you need to reach, what the HUD says, what they say, and
# what they hand you afterwards
MAIN = [
    dict(npc="ren", objective="Talk to Ren in Lowmarket", lines=[
        ("Ren", "There you are. The Static hit again last night. Every beacon in the Reach went dark."),
        ("Ren", "No beacons, no signals. The towns can't hear each other. Only couriers can carry word now."),
        ("Ren", "I'm too old for the skyways. You're not. Let's see you move."),
        ("Ren", "A and D to run, SPACE to jump. SHIFT dashes whichever way you're holding: up, down, diagonal."),
        ("Ren", "One dash at a time. Touch the ground and you get it back. Let go of everything and you stop dead."),
        ("Ren", "Take this letter to Mara at the far end of the market. Press E to talk to people."),
    ], gives="Ren's letter"),
    dict(npc="mara", objective="Deliver Ren's letter to Mara in Lowmarket", lines=[
        ("Mara", "From Ren? ...So he's finally sending someone out. Good."),
        ("Mara", "Cinder Hollow is east, down in the burning valley. Their forge can wind a beacon coil, but they'll want spice for it."),
        ("Mara", "Speed is everything out there. Hold S while running to slide. Jump out of a slide for a long jump."),
        ("Mara", "Courier's secret: dash diagonally down into the ground. That's a wavedash, and it turns into a fast slide."),
        ("Mara", "Wavedash, then turn around and jump right as you land, and you'll slingshot the other way. Here's the crate."),
    ], gives="Spice crate"),
    dict(npc="brask", objective="Deliver the spice crate to Brask in Cinder Hollow", lines=[
        ("Brask", "Spice! Mara's a saint. The forge has been cold since the Static."),
        ("Brask", "Here. An ember coil, still warm. The beacon on Mistral Spire needs it."),
        ("Brask", "The Spire is a long way up. Walls are your friends: hold toward one to slide down it, jump to kick off."),
        ("Brask", "Dash diagonally up into a wall and you'll run straight up it. Fall past a ledge holding toward it to grab on, then jump to vault."),
        ("Brask", "Oh, and dash straight down to slam the ground. Jump right after the slam and you'll bounce sky high."),
    ], gives="Ember coil"),
    dict(npc="isolde", objective="Bring the ember coil to Isolde atop Mistral Spire", lines=[
        ("Isolde", "You climbed the Spire carrying that? Impressive."),
        ("Isolde", "A climber's trick: shoot up past the top of a wall while holding toward it, and you whip over the corner with all that speed."),
        ("Isolde", "And run off a ledge, but jump at the very last moment. An edge jump gives you a burst of speed."),
        ("Isolde", "Take this weather vane to Tamsin on the Verdant Shelf. It floats, east of here."),
        ("Isolde", "Move fast just under its belly and you'll skim along it. Dash as you pass a corner to wrap around it and fling upward."),
    ], gives="Weather vane"),
    dict(npc="tamsin", objective="Deliver the weather vane to Tamsin on the Verdant Shelf", lines=[
        ("Tamsin", "The vane! Now we can read the Static's winds before they hit."),
        ("Tamsin", "Glasswater's lens-makers can grind a beacon lens, but it's a long, flat run. Keep your speed."),
        ("Tamsin", "Jump the instant you land to bunny hop. No friction, and a little faster every time."),
        ("Tamsin", "Falling fast? Hold S as you land to roll the fall into speed. Hit low lips at speed to corner-boost over them."),
        ("Tamsin", "Take this glass core to Orrin in Glasswater."),
    ], gives="Glass core"),
    dict(npc="orrin", objective="Bring the glass core to Orrin in Glasswater", lines=[
        ("Orrin", "A core this pure... I can grind the great lens from it. One moment."),
        ("Orrin", "There. This lens goes to the Keeper at Skyhold, at the very top of the sky. The great beacon sleeps there."),
        ("Orrin", "A few last tricks. Dash into a wall and jump right away to ricochet off it. Dash up into a ceiling to skate along it."),
        ("Orrin", "Jump during a ground dash for a dash hop. Low and long."),
        ("Orrin", "You know everything a courier can know. Go light the sky."),
    ], gives="Beacon lens"),
    dict(npc="keeper", objective="Carry the beacon lens to the Keeper at Skyhold", lines=[
        ("The Keeper", "So the Reach sent a courier after all."),
        ("The Keeper", "...The lens fits. Stand back."),
        ("The Keeper", "The great beacon is lit. Every town will see it now. The Static has nothing left to hide behind."),
        ("The Keeper", "But a beacon is only light. It's couriers who carry the world."),
        ("The Keeper", "The Dispatchers in every town will keep you busy. Run well."),
    ], gives=None),
]

JOB_ITEMS = ["Mail sack", "Lantern oil", "Spare gears", "Warm pie", "Sealed letter",
             "Map tube", "Seed packets", "Glass beads", "Rope coil", "Tea tin"]


class Quests:
    def __init__(self, towns, seed=3):
        self.towns = {t["id"]: t for t in towns}
        self.rng = random.Random(seed)
        self.step = 0
        self.item = None
        self.coins = 0
        self.job = None            # dict(item, to, reward, par, started)
        self.idle_i = {}

    @property
    def main_done(self):
        return self.step >= len(MAIN)

    def npc_pos(self, npc_id):
        n = NPCS[npc_id]
        t = self.towns[n["town"]]
        return t["x"] + n["dx"], t["plaza_y"]

    def main_target(self):
        return None if self.main_done else MAIN[self.step]["npc"]

    def job_target(self):
        return f"{self.job['to']}_disp" if self.job else None

    def objective(self):
        if self.main_done:
            return "Main story complete. Take jobs from any Dispatcher."
        return MAIN[self.step]["objective"]

    def talk(self, npc_id, now):
        """Returns the dialogue lines for talking to an NPC, applying
        whatever that conversation does."""
        n = NPCS[npc_id]
        if npc_id == self.main_target():
            step = MAIN[self.step]
            self.step += 1
            self.item = step["gives"]
            lines = list(step["lines"])
            if self.main_done:
                lines.append(("", "The great beacon is lit. Thanks for playing! The world is yours to run."))
            return lines
        if npc_id.endswith("_disp"):
            return self.dispatch(npc_id[:-5], now)
        i = self.idle_i.get(npc_id, 0)
        self.idle_i[npc_id] = i + 1
        return [(n["name"], n["idle"][i % len(n["idle"])])]

    def dispatch(self, town_id, now):
        name = "Dispatcher"
        here = self.towns[town_id]["name"]
        if self.job and self.job["to"] == town_id:
            took = now - self.job["started"]
            pay = self.job["reward"]
            lines = [(name, f"The {self.job['item'].lower()}! Signed and delivered.")]
            if took <= self.job["par"]:
                bonus = pay // 2
                lines.append((name, f"{took:.1f}s, under the {self.job['par']:.0f}s par. "
                                    f"Here's {pay} coins plus a {bonus} coin bonus."))
                pay += bonus
            else:
                lines.append((name, f"{took:.1f}s. Par was {self.job['par']:.0f}s. Here's your {pay} coins."))
            self.coins += pay
            self.job = None
            return lines
        if self.job:
            dest = self.towns[self.job["to"]]["name"]
            return [(name, f"You're still carrying a {self.job['item'].lower()} for {dest}. Get going!")]
        dest = self.rng.choice([t for t in TOWN_IDS if t != town_id])
        dist = abs(self.towns[dest]["x"] - self.towns[town_id]["x"]) + \
            abs(self.towns[dest]["plaza_y"] - self.towns[town_id]["plaza_y"])
        item = self.rng.choice(JOB_ITEMS)
        par = math.ceil(dist / 850 + 15)
        reward = 20 + dist // 500
        self.job = dict(item=item, to=dest, reward=reward, par=par, started=now)
        return [(name, f"Welcome to {here}. Got a {item.lower()} that needs to reach "
                       f"{self.towns[dest]['name']}."),
                (name, f"Pays {reward} coins. Beat {par}s and there's a bonus. Clock starts now!")]
