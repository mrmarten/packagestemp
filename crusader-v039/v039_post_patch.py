#!/usr/bin/env python3
"""Apply the v0.3.9 enemy-AI watchdog after the v0.3.7 source patch."""
from pathlib import Path
import sys


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def replace_function(path: Path, signature: str, next_signature: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"function start not found in {path}: {signature}")
    end = text.find(next_signature, start)
    if end < 0:
        raise SystemExit(f"next function not found in {path}: {next_signature}")
    path.write_text(text[:start] + body.rstrip() + "\n\n" + text[end:], encoding="utf-8", newline="\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: v039_post_patch.py <scummvm-source-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    actors = root / "engines/ultima/ultima8/world/actors"
    actor = actors / "actor.cpp"
    coop = actors / "cru_coop_mover_process.cpp"
    if not actor.is_file() or not coop.is_file():
        raise SystemExit("not a patched ScummVM/Ultima source tree")

    replace_exact(
        actor,
        "\tif (isDead() || World::get_instance()->getControlledNPCNum() == _objId\n"
        "\t\t|| hasActorFlags(ACT_WEAPONREADY) || activity == 0)\n"
        "\t\treturn 0;",
        "\t// Co-op AI recovery may rebuild a missing AttackProcess even when the\n"
        "\t// NPC already has its weapon-ready bit set.\n"
        "\tif (isDead() || World::get_instance()->getControlledNPCNum() == _objId ||\n"
        "\t\tactivity == 0)\n"
        "\t\treturn 0;",
        "allow co-op combat-state recovery",
    )
    replace_exact(
        actor,
        "\tif (_currentActivityNo == activity || (isInCombat() && activity != 0xc))\n"
        "\t\treturn 0;",
        "\t// A repeated attack activity can be a recovery request when the activity\n"
        "\t// number survived but the corresponding process did not.\n"
        "\tif (isInCombat() && activity != 0xc)\n"
        "\t\treturn 0;",
        "allow repeated attack recovery",
    )

    watchdog = r'''void CruCoopMoverProcess::updateEnemyAwareness() {
	MainActor *playerOne = getMainActor();
	Actor *playerTwo = getControlledActor();
	World *world = World::get_instance();
	CurrentMap *map = world ? world->getCurrentMap() : nullptr;
	Ultima8Engine *engine = Ultima8Engine::get_instance();
	if (!playerOne || !playerTwo || !map || !engine ||
		engine->isAvatarInStasis() || engine->isCruStasis() ||
		map->getNum() == COOP_REBEL_BASE_MAP ||
		playerOne->isDead() || playerTwo->isDead() ||
		playerOne->getMapNum() != playerTwo->getMapNum() ||
		playerOne->getMapNum() != map->getNum())
		return;

	// Crusader's passive AI was written around one globally controlled actor.
	// In co-op an NPC can already have ACT_INCOMBAT/activity=attack while the
	// corresponding AttackProcess is absent or stuck. Normalise every hostile
	// fast-area NPC exactly once per map/shape, then leave the live AttackProcess
	// alone so its draw/turn/path/aim/fire state can advance normally.
	static uint32 normalisedMap = 0xffffffff;
	static uint32 normalisedShape[256] = { 0 };
	static uint32 lastSummaryTick = 0;
	const uint32 mapNum = map->getNum();
	if (normalisedMap != mapNum) {
		normalisedMap = mapNum;
		for (uint i = 0; i < ARRAYSIZE(normalisedShape); ++i)
			normalisedShape[i] = 0;
		lastSummaryTick = 0;
		warning("Crusader co-op AI watchdog: map %u initialised", mapNum);
	}

	Kernel *kernel = Kernel::get_instance();
	uint32 fastActors = 0;
	uint32 hostileActors = 0;
	uint32 inRangeActors = 0;
	uint32 repairedActors = 0;
	uint32 activeAttackers = 0;

	for (uint actorId = 2; actorId < 256; ++actorId) {
		if (actorId == playerTwo->getObjId() ||
			actorId == World::get_instance()->getControlledNPCNum())
			continue;

		Actor *enemy = getActor(actorId);
		if (!enemy || enemy->isDead() ||
			enemy->hasActorFlags(Actor::ACT_COOP_PLAYER) ||
			!enemy->hasFlags(Item::FLG_FASTAREA) ||
			enemy->getMapNum() != mapNum ||
			enemy->getCurrentActivityNo() == 7)
			continue;
		++fastActors;

		const uint16 currentActivity = enemy->getCurrentActivityNo();
		const uint16 configuredReaction = enemy->getDefaultActivity(2);
		const bool hostileAlignment =
			(enemy->getEnemyAlignment() & playerOne->getAlignment()) != 0 ||
			(enemy->getEnemyAlignment() & playerTwo->getAlignment()) != 0;
		const bool attackProfile = isAttackActivity(currentActivity) ||
			isAttackActivity(configuredReaction) ||
			currentActivity == 8 || configuredReaction == 8;
		if (!hostileAlignment && !attackProfile && !enemy->isInCombat())
			continue;
		++hostileActors;

		Actor *target = selectEnemyTarget(enemy, 0, false);
		if (!target)
			continue;
		const int32 distance =
			enemy->getLocation().maxDistXYZ(target->getLocation());
		if (distance > 0x900)
			continue;
		++inRangeActors;

		AttackProcess *attack = enemy->getAttackProcess();
		const bool alreadyNormalised =
			normalisedShape[actorId] == enemy->getShape();
		if (alreadyNormalised && attack && enemy->isInCombat()) {
			++activeAttackers;
			Actor *currentTarget = getActor(attack->getTarget());
			if (!isPlayerTarget(currentTarget) || currentTarget->isDead() ||
				currentTarget->getMapNum() != mapNum)
				attack->setTarget(target->getObjId());
			continue;
		}

		// Rebuild all mutually dependent combat state in one transition. This
		// also repairs an NPC that says it is in combat but has no runnable
		// AttackProcess. Tactic 0 owns a complete Crusader attack loop.
		if (enemy->isInCombat())
			enemy->clearInCombat();
		static const uint16 processTypes[] = {
			ActorAnimProcess::ACTOR_ANIM_PROC_TYPE,
			0x0204, // PathfinderProcess
			0x0255, // PaceProcess
			0x0257, // LoiterProcess
			AttackProcess::ATTACK_PROC_TYPE,
			0x025e, // GuardProcess
			0x025f  // SurrenderProcess
		};
		for (uint p = 0; p < ARRAYSIZE(processTypes); ++p)
			kernel->killProcesses(enemy->getObjId(), processTypes[p], true);

		enemy->clearActorFlag(Actor::ACT_INCOMBAT | Actor::ACT_ANIMLOCK |
			Actor::ACT_PATHFINDING | Actor::ACT_SURRENDERED |
			Actor::ACT_WEAPONREADY);
		enemy->setCombatTactic(0);
		enemy->setActivity(5);
		attack = enemy->getAttackProcess();
		if (!attack) {
			normalisedShape[actorId] = 0;
			warning("Crusader co-op AI watchdog: actor %u shape %u could not create AttackProcess (activity=%u default2=%u)",
				enemy->getObjId(), enemy->getShape(), currentActivity,
				configuredReaction);
			continue;
		}

		attack->setTarget(target->getObjId());
		normalisedShape[actorId] = enemy->getShape();
		++repairedActors;
		warning("Crusader co-op AI watchdog: actor %u shape %u repaired against player %u (distance=%d activity=%u default2=%u alignment=%u enemyAlignment=%u)",
			enemy->getObjId(), enemy->getShape(), target->getObjId(), distance,
			currentActivity, configuredReaction, enemy->getAlignment(),
			enemy->getEnemyAlignment());
	}

	const uint32 now = Kernel::get_instance()->getTickNum();
	if (!lastSummaryTick || now - lastSummaryTick >= 300) {
		lastSummaryTick = now;
		warning("Crusader co-op AI watchdog: map %u fast=%u hostile=%u inRange=%u repaired=%u active=%u P1=%u P2=%u",
			mapNum, fastActors, hostileActors, inRangeActors, repairedActors,
			activeAttackers, playerOne->getObjId(), playerTwo->getObjId());
	}
}'''
    replace_function(
        coop,
        "void CruCoopMoverProcess::updateEnemyAwareness() {",
        "bool CruCoopMoverProcess::placeNearMainActor() {",
        watchdog,
    )

    marker = root / ".crusader-coop-v039"
    marker.write_text(
        "Crusader: No Remorse local co-op v0.3.9\n"
        "Enemy AI watchdog: distance-based activation plus one-time combat-state repair.\n",
        encoding="utf-8",
        newline="\n",
    )

    patched = coop.read_text(encoding="utf-8")
    required = [
        "Crusader co-op AI watchdog: map %u initialised",
        "normalisedShape[256]",
        "enemy->setCombatTactic(0);",
        "Crusader co-op AI watchdog: actor %u shape %u repaired",
        "distance > 0x900",
    ]
    missing = [needle for needle in required if needle not in patched]
    if missing:
        raise SystemExit(f"post-patch verification failed: {missing}")
    print("Applied Crusader co-op v0.3.9 AI watchdog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
