#!/usr/bin/env python3
"""Apply Crusader local co-op v0.4.0 controlled-actor/AI ownership fixes."""
from pathlib import Path
import sys


def replace_count(path: Path, old: str, new: str, label: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} match(es) in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    replace_count(path, old, new, label, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: v040_post_patch.py <scummvm-source-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    actors = root / "engines/ultima/ultima8/world/actors"
    coop = actors / "cru_coop_mover_process.cpp"
    actor = actors / "actor.cpp"
    attack = actors / "attack_process.cpp"
    for path in (coop, actor, attack):
        if not path.is_file():
            raise SystemExit(f"missing patched source file: {path}")

    replace_exact(
        coop,
        '''bool CruCoopMoverProcess::isPlayerTarget(const Actor *actor) {
\tif (!actor)
\t\treturn false;
\treturn actor == ::Ultima::Ultima8::getControlledActor() ||
\t\tactor->hasActorFlags(Actor::ACT_COOP_PLAYER);
}''',
        '''bool CruCoopMoverProcess::isPlayerTarget(const Actor *actor) {
\tif (!actor)
\t\treturn false;
\treturn actor == getMainActor() || actor == getPlayerTwo() ||
\t\tactor->hasActorFlags(Actor::ACT_COOP_PLAYER);
}''',
        "identify the actual two local players",
    )

    replace_exact(
        coop,
        '''\tActor *candidates[] = {
\t\t::Ultima::Ultima8::getControlledActor(),
\t\tgetPlayerTwo()
\t};''',
        '''\tActor *candidates[] = {
\t\tgetMainActor(),
\t\tgetPlayerTwo()
\t};''',
        "target actual P1 instead of transient controlled NPC",
    )

    replace_exact(
        coop,
        '''\tfor (uint actorId = 2; actorId < 256; ++actorId) {
\t\tif (actorId == playerTwo->getObjId() ||
\t\t\tactorId == World::get_instance()->getControlledNPCNum())
\t\t\tcontinue;''',
        '''\tfor (uint actorId = 2; actorId < 256; ++actorId) {
\t\t// The original game can temporarily set controlledNPCNum to a mission
\t\t// NPC. In local co-op that NPC is still an enemy; skip only the two
\t\t// actors that are actually controlled by the local players.
\t\tif (actorId == playerOne->getObjId() ||
\t\t\tactorId == playerTwo->getObjId())
\t\t\tcontinue;''',
        "do not discard a guard merely because usecode marked it controlled",
    )

    replace_exact(
        coop,
        '''\t\twarning("Crusader co-op AI watchdog: map %u fast=%u hostile=%u inRange=%u repaired=%u active=%u P1=%u P2=%u",
\t\t\tmapNum, fastActors, hostileActors, inRangeActors, repairedActors,
\t\t\tactiveAttackers, playerOne->getObjId(), playerTwo->getObjId());''',
        '''\t\twarning("Crusader co-op AI watchdog: map %u fast=%u hostile=%u inRange=%u repaired=%u active=%u P1=%u P2=%u controlled=%u",
\t\t\tmapNum, fastActors, hostileActors, inRangeActors, repairedActors,
\t\t\tactiveAttackers, playerOne->getObjId(), playerTwo->getObjId(),
\t\t\tworld->getControlledNPCNum());''',
        "log the engine controlled NPC number",
    )

    replace_exact(
        coop,
        '''\tif (!playerOne || playerOne->isDead() || !engine ||
\t\tengine->isAvatarInStasis() || engine->isCruStasis()) {
\t\tresetMovementFlags();
\t\treturn;
\t}

\tsyncSharedState();''',
        '''\tif (!playerOne || playerOne->isDead() || !engine ||
\t\tengine->isAvatarInStasis() || engine->isCruStasis()) {
\t\tresetMovementFlags();
\t\treturn;
\t}

\t// Crusader's single-player AI treats controlledNPCNum as the player and
\t// refuses to attack that actor. Mission usecode can temporarily leave this
\t// value on a guard/NPC. Co-op always controls P1 through the MainActor and P2
\t// through this process, so restore the single-player owner before AI runs.
\tWorld *coopWorld = World::get_instance();
\tif (coopWorld && coopWorld->getControlledNPCNum() != kMainActorId) {
\t\twarning("Crusader co-op: normalising controlled NPC from %u to P1 actor %u",
\t\t\tcoopWorld->getControlledNPCNum(), kMainActorId);
\t\tcoopWorld->setControlledNPCNum(kMainActorId);
\t}

\tsyncSharedState();''',
        "normalise controlled NPC before AI update",
    )

    replace_exact(
        actor,
        '''\tif (isDead() || World::get_instance()->getControlledNPCNum() == _objId ||
\t\tactivity == 0)
\t\treturn 0;''',
        '''\tif (isDead() || _objId == kMainActorId ||
\t\thasActorFlags(ACT_COOP_PLAYER) || activity == 0)
\t\treturn 0;''',
        "setActivityCru player ownership check",
    )

    replace_exact(
        actor,
        '''\tif (shape != 1 && this != getControlledActor() && !hasActorFlags(ACT_COOP_PLAYER)) {''',
        '''\tif (_objId != kMainActorId && !hasActorFlags(ACT_COOP_PLAYER)) {''',
        "receiveHitCru actual-player exclusion",
    )

    replace_exact(
        actor,
        '''\tif (getObjId() == World::get_instance()->getControlledNPCNum())
\t\treturn;''',
        '''\tif (getObjId() == kMainActorId)
\t\treturn;''',
        "setInCombatCru actual-player exclusion",
    )

    replace_count(
        actor,
        '''\tActor *playerOne = ::Ultima::Ultima8::getControlledActor();
\tActor *playerTwo = CruCoopMoverProcess::getPlayerTwo();''',
        '''\tActor *playerOne = getMainActor();
\tActor *playerTwo = CruCoopMoverProcess::getPlayerTwo();''',
        "co-op P1 references use MainActor",
        2,
    )

    replace_exact(
        actor,
        '''\tconst Actor *controlled = ::Ultima::Ultima8::getControlledActor();
\tif (!controlled)
\t\treturn false;''',
        '''\tconst Actor *controlled = getMainActor();
\tif (!controlled)
\t\treturn false;''',
        "canSeeControlledActor uses MainActor",
    )

    replace_exact(
        attack,
        '''\t// This should never be running on the controlled npc.
\tif (_itemNum == World::get_instance()->getControlledNPCNum()) {
\t\tterminate();
\t\treturn;
\t}''',
        '''\t// In co-op, mission usecode may temporarily leave controlledNPCNum on
\t// an enemy NPC. Only the two real local-player actors are excluded.
\tActor *processActor = getActor(_itemNum);
\tif (_itemNum == kMainActorId ||
\t\t(processActor && processActor->hasActorFlags(Actor::ACT_COOP_PLAYER))) {
\t\tterminate();
\t\treturn;
\t}''',
        "genericAttack actual-player exclusion",
    )

    marker = root / ".crusader-coop-v040"
    marker.write_text(
        "Crusader: No Remorse local co-op v0.4.0\n"
        "AI ownership fix: P1 is MainActor, P2 is ACT_COOP_PLAYER; transient controlledNPCNum no longer hides guards.\n",
        encoding="utf-8",
        newline="\n",
    )

    checks = {
        coop: [
            "normalising controlled NPC from %u to P1 actor %u",
            "actorId == playerOne->getObjId()",
            "controlled=%u",
            "getMainActor(),\n\t\tgetPlayerTwo()",
        ],
        actor: [
            "_objId == kMainActorId",
            "const Actor *controlled = getMainActor();",
            "Actor *playerOne = getMainActor();",
        ],
        attack: [
            "mission usecode may temporarily leave controlledNPCNum on",
            "processActor->hasActorFlags(Actor::ACT_COOP_PLAYER)",
        ],
    }
    for path, needles in checks.items():
        text = path.read_text(encoding="utf-8")
        missing = [needle for needle in needles if needle not in text]
        if missing:
            raise SystemExit(f"post-patch verification failed in {path}: {missing}")

    print("Applied Crusader co-op v0.4.0 controlled-actor AI ownership fix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
