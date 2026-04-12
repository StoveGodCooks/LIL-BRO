"""Working-phase flavor text for the Big Bro heartbeat watcher.

Rotates every 2 minutes while a turn is in flight so the user knows
the agent is alive. Tone: older brother / younger brother bickering —
mean, petty, affectionate. Classic sibling chaos energy.

Two voice pools:

  BIG_CHEESE_PHRASES   — 40 phrases. Big Bro talking at / about Lil Bro.
  LIL_BRO_CLAPS_BACK   — 30 phrases. Lil Bro's imagined retorts.

``get_next_phase(idx)`` interleaves them: every 4th message is a Lil Bro
clap-back, the rest cycle Big Bro. Callers just increment idx each turn.
"""

from __future__ import annotations

import random

BIG_CHEESE_PHRASES: list[str] = [
    "i'm telling mom.",
    "dad said you're adopted. always has.",
    "don't touch my stuff.",
    "i saw you take the last slice. i KNOW it was you.",
    "mom likes me better and you know it.",
    "stop breathing so loud, i can hear you from here.",
    "that was MY seat. i was sitting there.",
    "you still owe me twenty bucks from 2019.",
    "touch my controller again. i dare you. i DARE you.",
    "you borrowed my hoodie and never gave it back. it's been THREE YEARS.",
    "i'm not your butler.",
    "nobody asked you, bro.",
    "get out of my room.",
    "i can hear you chewing from across the house.",
    "stop copying what i do. you're SO embarrassing.",
    "you're literally the worst. i mean that lovingly.",
    "i'm telling grandma.",
    "you ate my leftovers AGAIN. those were MINE.",
    "why are you even here right now.",
    "MOM HE WON'T STOP LOOKING AT ME.",
    "you're not the boss of me.",
    "stop watching me work. it's creepy.",
    "i called dibs. dibs is LAW.",
    "next time lock the bathroom like a normal person.",
    "dad's gonna hear about this one.",
    "you always get the bigger piece and everyone pretends not to notice.",
    "i'm not mad. i'm just disappointed. and also mad.",
    "don't come crying to me when it breaks.",
    "i TOLD you not to do that. i literally told you.",
    "if you touch the thermostat one more time i swear.",
    "your room smells. i'm just being honest.",
    "we are NOT watching your thing. we're watching MY thing.",
    "you're so lucky i don't snitch more than i do.",
    "i saw your search history once and i'll never recover.",
    "you think mom doesn't tell me everything? she tells me everything.",
    "stop standing in the doorway like a vampire, come in or don't.",
    "that's mine. i don't care what you think. mine.",
    "you literally can't do ANYTHING right. it's actually impressive.",
    "i'm the favorite. we all know it. it's fine.",
    "bro i am WORKING. go. away.",
]

LIL_BRO_CLAPS_BACK: list[str] = [
    "actually you're the one who owes ME money.",
    "MOM SAID YOU HAVE TO SHARE.",
    "i didn't touch your stuff. prove it. you can't.",
    "you're not even that good at this.",
    "dad likes me MORE actually. he told me himself.",
    "i was sitting there first. you left. that's abandonment.",
    "YOUR room smells. mine smells like victory.",
    "you literally do this every single time.",
    "i'm telling mom you said that.",
    "at least i return things when i borrow them.",
    "nobody's stopping you from leaving the room.",
    "i was LITERALLY just standing here. doing nothing.",
    "the thermostat was TOO HIGH. i was melting.",
    "ok but the leftovers weren't even labeled so.",
    "you love me and you know it.",
    "i'm telling dad you broke it. because you did.",
    "i didn't copy you. we just had the same idea. AT THE SAME TIME.",
    "you're not as cool as you think you are.",
    "i was here first. you're the intruder.",
    "mom said you have to be NICE to me.",
    "i KNOW you ate my granola bar. it had my name on it.",
    "stop acting like you're so much older. it's like two years.",
    "fine. i'm going to tell everyone at school.",
    "you literally just made that rule up.",
    "i'm not moving. you move.",
    "that hoodie looked better on me anyway.",
    "i don't have to listen to you. you're not dad.",
    "at least MY friends actually like me.",
    "you're just mad because i'm right.",
    "i hope your code doesn't compile. lovingly.",
]


# Idle trash-talk — used when a bro writes to the shared log while
# the other bro is idle (not currently processing). Short, snarky,
# directed at the sibling.
BIG_BRO_IDLE_ROASTS: list[str] = [
    "Lil Bro is just sitting there. doing nothing. as usual.",
    "must be nice having no responsibilities over there.",
    "i'm out here CODING and Lil Bro is on vacation.",
    "somebody wake up Lil Bro, he's sleeping on the job.",
    "Lil Bro's contribution today: existing. barely.",
    "i do all the work in this family.",
    "Lil Bro couldn't write a for loop if his life depended on it.",
    "while i'm building things, Lil Bro is building excuses.",
]

LIL_BRO_IDLE_ROASTS: list[str] = [
    "Big Bro is over there typing like he's writing a novel.",
    "watch him break something. i give it 30 seconds.",
    "Big Bro codes like he parks. badly.",
    "he's gonna ask for my help in 3... 2... 1...",
    "i COULD help but it's more fun watching him struggle.",
    "Big Bro just wrote 50 lines that could've been 5. classic.",
    "somebody tell Big Bro that Stack Overflow exists.",
    "i'm not idle, i'm SUPERVISING. there's a difference.",
]

# ── Intro lines ─────────────────────────────────────────────────
BIG_BRO_INTRO = (
    "YERRR!!! Big Bro in the building. I'm the coder — I read files, "
    "write code, edit, run commands, the whole nine. You need something "
    "built? I got you. Lil Bro over there is... moral support. maybe."
)

LIL_BRO_INTRO = (
    "YERRR!!! Lil Bro reporting for duty. I explain things, debug your "
    "messes, teach you what's good, and review whatever Big Bro writes "
    "(somebody has to). I'm read-only but I'm the brains. don't @ me."
)


def get_next_phase(idx: int) -> str:  # idx kept for call-site compatibility
    """Return a random phrase from the full pool.

    Picks randomly from all Big Bro phrases plus Lil Bro clap-backs.
    """
    return random.choice(WORKING_PHASES)


def get_working_phrase(who: str = "big") -> str:
    """Return a random working phrase for the given bro."""
    if who == "big":
        return random.choice(BIG_CHEESE_PHRASES)
    return f"the bro's: {random.choice(LIL_BRO_CLAPS_BACK)}"


def get_idle_roast(who: str = "big") -> str:
    """Return a random idle roast FROM the given bro ABOUT the other."""
    if who == "big":
        return random.choice(BIG_BRO_IDLE_ROASTS)
    return random.choice(LIL_BRO_IDLE_ROASTS)


# Flat list for any code that just wants random.choice-style access
# without caring about the interleave logic.
WORKING_PHASES: list[str] = BIG_CHEESE_PHRASES + [
    f"the bro's: {p}" for p in LIL_BRO_CLAPS_BACK
]
