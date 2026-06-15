#!/usr/bin/env python3
"""NEON KERNEL 자동 검증 하네스 (Playwright / Python)

이 환경엔 node가 없어 JS용 Playwright 대신 Python Playwright를 쓴다.
실제 브라우저로 prototype/index.html 을 띄워:
  1) 콘솔 에러 / 페이지 예외(throw) 를 수집
  2) 게임 RAF(loop: update→render)가 살아있는지(G.t 증가) 확인
     → CLAUDE.md 교훈: 렌더 크래시는 RAF를 멈춘다. G.t 정지로 잡는다.
  3) 신규/주요 코드 경로를 강제 구동(기체 5종, 압축 훅, 딥웹 룰렛,
     저주 슬롯잠금, 신규 렌더 분기)해서 그 와중에 에러가 안 나는지 확인

사용:
  python tools/verify_game.py                # 기본(headless)
  python tools/verify_game.py --headed       # 화면 띄워서
  python tools/verify_game.py --seconds 4    # 라이브 구동 시간

종료코드: 0=PASS, 1=FAIL(에러 또는 RAF 정지)
"""
import sys, time, pathlib, argparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "prototype" / "index.html"

# 페이지 안에서 실행할 드라이브 스크립트.
# 모든 신규 코드 경로를 합성으로 강제 실행하고, 던지면 {ok:false, where, msg} 반환.
DRIVE_JS = r"""
() => {
  const log = [];
  const step = (where, fn) => { try { fn(); log.push("OK   "+where); }
    catch(e){ log.push("FAIL "+where+": "+(e&&e.stack||e)); throw Object.assign(new Error(where+": "+e), {where}); } };
  try {
    step("boot", () => { try { localStorage.clear(); } catch (e) {} SAVE = defaultSave(); newGame(); }); // 결정성 위해 SAVE 초기화 + 부팅
    step("globals-present", () => {
      for (const n of ["G","CHASSIS","setChassisIndex","rollDeepweb","canCompress","SAVE","goScene",
                       "applyChassisToCore","reapplyChassisToAllCores","makeT1Id","newGame","metaRunMods"]) {
        if (typeof eval(n) === "undefined") throw new Error("missing global: "+n);
      }
    });

    // 기체 5종 전부: 전환 + 코어 재적용 + 각 기체 압축 훅 + 신규 렌더 상태 주입
    for (let i = 0; i < CHASSIS.length; i++) {
      const ch = CHASSIS[i];
      step("setChassis:"+ch.id, () => setChassisIndex(i));

      // 압축 성공 훅(광랜 복리 reapply / 딥웹 룰렛)이 던지지 않는지
      step("onCompress:"+ch.id, () => {
        const core = makeT1Id("streamPing");
        applyChassisToCore(core);
        if (G.chassis && G.chassis.onCompressionSuccess) G.chassis.onCompressionSuccess(G, core, {});
      });

      // 신규 렌더 분기를 강제로 켠다 (실제 RAF가 다음 프레임에 그린다)
      step("inject-render-state:"+ch.id, () => {
        G.shield = (G.shieldMax || 12) * 0.5;     // 프록시 보호막 링
        G.glitchCooldown = 0.3;                    // 글리치 과열 플리커
        if (G.slots[0]) { G.slots[0].deepweb = "curse"; G.slots[0].cursed = true; } // 딥웹 저주 마커
        if (G.slots[2]) { G.slots[2].deepweb = "jackpot"; }                          // 딥웹 대박 마커
      });
    }

    // 딥웹 룰렛: 3분기(대박/중간/저주)가 모두 던지지 않는지 — 확률 강제 주입
    step("rollDeepweb-branches", () => {
      const real = Math.random;
      for (const r of [0.05, 0.45, 0.95]) {          // jackpot / normal / curse
        Math.random = () => r;
        const c = makeT1Id("dotSnippet"); applyChassisToCore(c); rollDeepweb(c);
        if (!c.deepweb) throw new Error("rollDeepweb set no flag at r="+r);
      }
      Math.random = real;
    });

    // 저주 슬롯 잠금: cursed 코어는 canCompress가 null
    step("cursed-lock", () => {
      const a = makeT1Id("streamPing"), b = makeT1Id("streamPing");
      a.cursed = true;
      if (canCompress(a, b) !== null) throw new Error("cursed core still compressable");
      const c = makeT1Id("streamPing"), d = makeT1Id("streamPing");
      if (canCompress(c, d) === null) throw new Error("same-color T1 should compress");
    });

    // Affix 스탯 레이어: 거대한=bulletR↑dmg↑, 과부하=dmg↑. fx 플래그 세팅.
    step("affix-stat-layer", () => {
      const c = makeT1Id("streamPing");
      const b0 = { dmg: c.dmg, br: c.bulletR };
      setAffixes(c, { prefix: "giant", suffix: "overload" });
      if (!(c.dmg > b0.dmg) || !(c.bulletR > b0.br)) throw new Error("giant/overload should raise dmg/bulletR");
      setAffixes(c, null);
      if (Math.abs(c.dmg - b0.dmg) > 1e-6) throw new Error("affix clear should restore base dmg");
    });

    // Affix fx 플래그: crit/vulnOnHit/affixFrag/lifesteal/ddos가 affixFx에 실림
    step("affix-fx-flags", () => {
      const checks = [["crit","crit"],["format","vulnOnHit"],["split","affixFrag"],["drain","lifesteal"],["ddos","ddos"]];
      for (const [aff, key] of checks) {
        const c = makeT1Id("streamPing");
        const isPrefix = (aff==="split");
        setAffixes(c, isPrefix ? { prefix: aff } : { suffix: aff });
        if (!c.affixFx || c.affixFx[key] == null) throw new Error(aff+" → affixFx."+key+" 누락");
      }
    });

    // Affix bparam 일관성: beam 코어 + 거대한(dmg×1.3) → beamDmgps도 스케일 (base.dmg=0 probe 경로)
    step("affix-beam-scale", () => {
      const spec = T2_CORES.find(s => s.behavior === "beam");
      if (!spec) return;
      const c = makeT2FromIds(spec.parents[0], spec.parents[1]);
      const base = c.bparams.beamDmgps;
      setAffixes(c, { prefix: "giant" }); // dmg×1.3
      if (!(c.bparams.beamDmgps > base * 1.2)) throw new Error("거대한이 beamDmgps도 스케일해야(현=" + c.bparams.beamDmgps + ")");
    });

    // random/curse 헬퍼
    step("affix-random-curse", () => {
      const a = makeT1Id("dotSnippet"); setAffixes(a, "random");
      if (!hasAffix(a)) throw new Error("random affix 미적용");
      const b = makeT1Id("dotSnippet"); setAffixes(b, "curse");
      if (!isNegAffix(b.affixes)) throw new Error("curse는 neg여야");
    });

    // 유형C 모듈: addAffix는 단일 슬롯만 설정(나머지 보존), rollAffixModule은 양수만
    step("affix-module", () => {
      const c = makeT1Id("streamPing");
      addAffix(c, "prefix", "giant"); addAffix(c, "suffix", "crit");
      if (c.affixes.prefix !== "giant" || c.affixes.suffix !== "crit") throw new Error("addAffix 슬롯 보존 실패");
      for (let i = 0; i < 20; i++) { const m = rollAffixModule();
        if (!AFFIX_BY_ID[m.id] || AFFIX_BY_ID[m.id].kind === "neg") throw new Error("모듈 보상에 마이너스/무효"); }
    });

    // 유형C 보상 흐름: 후보→대상선택(boost단계, T3 한정)→부착 (orbitConfirm 경로)
    step("affix-reward-flow", () => {
      G.slots[0] = makeCore(3, ["mint", "red"]); // Affix 부착 대상은 T3 한정
      enterOrbit();
      G.candidates[0] = { core: null, boost: null, affix: rollAffixModule(), ang: 0, r: CFG.candidateR, taken: false, bob: 0 };
      G.selCandIdx = 0;
      orbitConfirm();
      if (G.orbitStep !== "boost") throw new Error("affix 후보 확정→대상선택 단계 실패");
      if (!affixableSlots().length) throw new Error("T3 대상 목록이 비어있음");
      orbitConfirm();
      if (!G.slots.some(c => c && c.tier === 3 && hasAffix(c))) throw new Error("T3 코어 affix 부착 실패");
    });

    // T3 한정 검증: T1만 있으면 affixableSlots 비고, 등장조건 hasT3 거짓
    step("affix-t3-only", () => {
      newGame(); G.slots = [makeT1Id("streamPing"), null, null, null, null, null];
      if (affixableSlots().length !== 0) throw new Error("T1만 있는데 affix 대상이 잡힘");
      G.slots[2] = makeCore(3, ["mint", "purple"]);
      if (affixableSlots().length !== 1) throw new Error("T3 장착 후 affix 대상 1개여야");
    });

    // SF 토스트(일시, 합성결과용)
    step("toast", () => {
      G.toasts = []; pushToast("스트리밍(T2)", "straight", "#7fe9ff");
      if (!G.toasts.length) throw new Error("pushToast 실패");
    });

    // 조준 팝업: 정비궤도 진입 시 설정 → 탁으로 갱신 → 보상 확정 시 해제
    step("aim-popup", () => {
      if (!G.slots.some(c => c)) G.slots[0] = makeT1Id("streamPing");
      enterOrbit();
      if (!G.aimToast || !G.aimToast.name) throw new Error("진입 시 조준 팝업 미설정");
      orbitTap();
      if (!G.aimToast) throw new Error("탁 후 조준 팝업 사라짐");
      orbitConfirm();
      if (G.aimToast) throw new Error("보상 확정 후에도 조준 팝업 잔류");
    });

    // ===== 빔(레이저) 버그 수정 회귀 =====
    step("beam-intercepts-ebullet", () => {
      newGame();
      const spec = T2_CORES.find(s => s.behavior === "beam");
      G.slots[0] = makeT2FromIds(spec.parents[0], spec.parents[1]);
      G.bullets = []; G.ebullets = [];
      fireSlot(0);
      const beam = G.bullets.find(b => b.behavior === "beam");
      if (!beam) throw new Error("빔 미생성");
      const ex = beam.x + Math.cos(beam.angle) * 100, ey = beam.y + Math.sin(beam.angle) * 100;
      G.ebullets.push({ x: ex, y: ey, vx: 0, vy: 0, life: 1, r: 4 });
      collide(0.016);
      if (G.ebullets[0].life > 0) throw new Error("빔이 적탄을 요격 못함");
    });
    step("beam-no-stack", () => {
      newGame();
      const spec = T2_CORES.find(s => s.behavior === "beam");
      const c = makeT2FromIds(spec.parents[0], spec.parents[1]);
      G.slots[0] = c; G.bullets = [];
      fireSlot(0);
      const beam = G.bullets.find(b => b.behavior === "beam");
      // life가 발사주기(interval×1.1)에 맞아야 — 과거 고정 0.06이면 중첩 누적
      if (beam.life > c.interval * 1.2 + 1e-6) throw new Error("빔 life가 발사주기보다 김(중첩): " + beam.life);
    });

    // ===== 보스 (정의서 11.1) =====
    step("boss-spawn-3", () => {
      for (const [w, kind] of [[10, "walle"], [20, "antiv"], [30, "panic"]]) {
        newGame(); startWave(w);
        if (!G.boss || G.boss.kind !== kind) throw new Error("보스 미스폰: " + kind);
        if (G.waveBudgetLeft !== 0) throw new Error("보스전인데 일반 예산 존재");
        updateBoss(0.1); // 기믹 1틱(크래시 체크)
      }
    });
    step("boss-walle-shield", () => {
      newGame(); startWave(10); const b = G.boss; b.shieldRot = 0;
      if (!walleBlocks(b, 0)) throw new Error("방패 중심인데 차단 안됨");
      if (walleBlocks(b, Math.PI)) throw new Error("틈(π)인데 차단됨");
    });
    step("boss-defeat-mid-super", () => {
      newGame(); startWave(10); G.boss.hp = 0; updateBoss(0.1);
      if (G.boss) throw new Error("보스 미처치");
      if (G.phase !== "orbit" || !G.superOrbit) throw new Error("중간보스 처치→슈퍼 정비궤도 아님");
      if (G.candidates.length !== 6) throw new Error("슈퍼 후보 6개 아님: " + G.candidates.length);
      if (G.orbitPicksLeft !== 2) throw new Error("슈퍼 픽 2 아님");
    });
    step("boss-defeat-final-clear", () => {
      newGame(); startWave(30); G.boss.hp = 0; G.ended = false; updateBoss(0.1);
      if (scene !== "result" || !lastResult.cleared) throw new Error("최종보스 처치→클리어 아님");
      if (!SAVE.cleared) throw new Error("SAVE.cleared 미설정");
    });

    // ===== 보스 시그니처 텔레그래프 공격 (정의서 3.7/11.1) =====
    step("boss-special-attacks", () => {
      for (const [w, kind, minBolts] of [[10, "walle", 1], [20, "antiv", 3], [30, "panic", 8]]) {
        newGame(); startWave(w); const b = G.boss; G.ebullets = [];
        b.atkT = 0; bossSpecial(b, 0.016);                       // 텔레그래프 시작
        if (!b.tele) throw new Error(kind + " 텔레그래프 미시작");
        let guard = 0; while (b.tele && guard++ < 400) bossSpecial(b, 0.05); // 차징 완료→발사
        if (G.ebullets.length < minBolts) throw new Error(kind + " 인바운드 탄 부족: " + G.ebullets.length);
        const eb = G.ebullets[0];                                 // 탄은 중심을 향해야(요격 가능)
        if (eb.vx * (CX - eb.x) + eb.vy * (CY - eb.y) <= 0) throw new Error(kind + " 탄이 중심을 안 향함");
        if (!eb.boss) throw new Error(kind + " 보스탄 플래그 누락");
        // walle: 탄류가 보스 쪽에서 출발해야(반대편 스폰 버그 회귀)
        if (kind === "walle" && ((eb.x - CX) * (b.x - CX) + (eb.y - CY) * (b.y - CY)) <= 0)
          throw new Error("walle 탄이 보스 반대편에서 스폰");
        // 스폰 반경은 화면 비례여야(모바일 일관) — 화면 대각 밖 고정픽셀 금지
        if (Math.hypot(eb.x - CX, eb.y - CY) > Math.min(W, H) * 0.65) throw new Error(kind + " 스폰 반경이 화면 비례 아님");
      }
    });
    step("boss-phase2-faster", () => {
      newGame(); startWave(30); const b = G.boss;
      const p1 = bossAtkPeriod(b); b.phase = 2; const p2 = bossAtkPeriod(b);
      if (!(p2 < p1)) throw new Error("페이즈2 공격주기가 더 짧아야: " + p1 + "→" + p2);
    });
    step("boss-special-defendable", () => {
      // panic 수축 링엔 틈(안전 각도)이 있어야 — 전부 막히면 노히트 불가(11.2 원칙)
      newGame(); startWave(30); const b = G.boss; G.ebullets = [];
      b.atkT = 0; bossSpecial(b, 0.016); let g = 0;
      while (b.tele && g++ < 400) bossSpecial(b, 0.05);
      const N = 36, full = N; // 틈 없으면 36발
      if (G.ebullets.length >= full) throw new Error("수축 링에 틈이 없음(노히트 불가)");
    });

    // ===== 이어하기 (정의서 9.5) — 보스전 1회 한정 =====
    step("revive-boss-offer", () => {
      newGame(); startWave(20); G.hp = 0; die();
      if (!G.dead || !G.reviveOffer) throw new Error("보스전 사망인데 이어하기 오퍼 없음");
      const hp = G.hpMax * 0.5; reviveRun();
      if (G.dead || G.reviveOffer) throw new Error("이어하기 후에도 사망 상태");
      if (!G.boss) throw new Error("이어하기 후 보스 사라짐(빌드/전투 유지 실패)");
      if (Math.abs(G.hp - hp) > 1e-6) throw new Error("이어하기 체력 절반 회복 아님: " + G.hp);
      if (!G.continueUsed) throw new Error("continueUsed 미설정");
      // 판당 1회: 두 번째 보스전 사망엔 오퍼 없음
      G.hp = 0; die();
      if (G.reviveOffer) throw new Error("판당 2회째 이어하기 오퍼가 떠선 안 됨");
    });
    step("revive-nonboss-skip", () => {
      newGame(); G.boss = null; G.hp = 0; die();
      if (G.reviveOffer) throw new Error("일반 웨이브 사망엔 이어하기 오퍼 없어야");
    });

    // ===== 실입력 체인 (pressDown/pressUp 경유 — 함수 직접 호출만으론 입력 버그를 못 잡는다) =====
    step("input-brake-instant", () => {
      SAVE.chassis = "legacy"; startGame(); const dir0 = G.dir, hp0 = G.hp;
      pressDown();
      if (!G.braking) throw new Error("누르는 즉시 브레이크가 아님(반응 지연)");
      update(0.05);                                  // held 0.05 < TAP_MAX → 탁으로 분류돼야
      pressUp();
      if (G.braking) throw new Error("탭 후 브레이크 잔류");
      if (G.dir !== -dir0) throw new Error("탭=회전반전 미동작");
      if (G.hp < hp0 - 1e-9) throw new Error("탭(TAP_MAX 이하)에 드레인 부과: " + (hp0 - G.hp));
    });
    step("input-brake-drain-gate", () => {
      startGame(); const hp0 = G.hp, dir0 = G.dir;
      pressDown();
      for (let f = 0; f < 60; f++) update(1 / 60);   // 1초 홀드 = 꾹
      if (!G.braking) throw new Error("홀드 중 브레이크 해제됨");
      if (!(G.hp < hp0)) throw new Error("1초 홀드인데 드레인 없음(비용 소실)");
      pressUp();
      if (G.dir !== dir0) throw new Error("꾹 해제가 회전반전을 일으킴");
    });
    step("input-grace-tap-free", () => {
      // grace(0.5s) 재진입 탭: brakeTime이 높게 이월돼도 '탁 플릭'은 드레인 0(탭=무비용 일관성)
      startGame();
      pressDown();
      for (let f = 0; f < 120; f++) update(1 / 60);   // 2초 홀드 → brakeTime 누적(드레인 단계 진입)
      pressUp();                                       // releaseGrace=0.5 + brakeTime 보존
      pressDown();                                     // grace 내 재진입(brakeTime 이월=높음)
      if (G.brakeTime < 1.0) throw new Error("grace 재진입인데 brakeTime이 보존 안 됨: " + G.brakeTime);
      const hp0 = G.hp;
      update(0.05);                                    // 이번 누름 held<TAP_MAX → 게이트 차단
      if (G.hp < hp0 - 1e-9) throw new Error("grace 재진입 탭에 드레인 부과(탭=무비용 위반): " + (hp0 - G.hp));
      pressUp();
    });
    step("input-revive-chain", () => {
      startGame(); startWave(20); G.hp = 0; die();
      if (!G.reviveOffer) throw new Error("보스전 사망 오퍼 없음");
      pressDown();                                   // 사망 직후(arming 0.5s 전) 연타 → 무시
      if (!G.dead) throw new Error("arming 전 탭이 이어하기를 소모");
      for (let f = 0; f < 40; f++) update(1 / 60);   // 0.67s 경과(오퍼 6s 내)
      pressDown();                                   // 실입력 탭 = 이어하기
      if (G.dead) throw new Error("실입력 탭으로 이어하기 미발동");
      if (!G.boss) throw new Error("이어하기 후 보스 소실");
      const dir0 = G.dir;
      G.hp = 0; die();                               // 판당 1회 소진 → 오퍼 없음
      if (G.reviveOffer) throw new Error("이어하기 2회 오퍼");
      // 사망 시점에 '짧게' 누르고 있던 손가락의 release: held<TAP_MAX라도 사망 중이면 무동작이어야
      // (pressStart를 stale로 두면 held가 커져 탁 분기를 우회 → 가드 회귀를 못 잡는 공허한 단언이 됨)
      pressing = true; pressStart = G.t - 0.05; pressUp();
      if (scene !== "game") throw new Error("사망 중 release가 정산 등 동작 유발");
      if (G.dir !== dir0) throw new Error("사망 중 release가 회전반전을 일으킴");
      for (let f = 0; f < 40; f++) update(1 / 60);
      if (G.ended) throw new Error("이 시점 G.ended는 false여야(정산 미발생)"); // 강제 리셋 제거: 회귀 감지
      pressDown();                                   // arming 후 탭 = 정산 스킵
      if (scene !== "result") throw new Error("사망 탭 정산 스킵 실패");
    });
    step("input-orbit-chain", () => {
      // 정비궤도 입력도 실입력 경유 검증(pressDown의 phase 가드가 깨지면 후보 선택이 망가짐)
      startGame(); G.slots[0] = makeT1Id("streamPing"); enterOrbit();
      if (G.phase !== "orbit") throw new Error("정비궤도 진입 실패");
      pressDown();
      if (G.braking) throw new Error("정비궤도에서 pressDown이 브레이크 진입(전투 전용 가드 깨짐)");
      const idx0 = G.selCandIdx;
      pressUp();                                      // 짧은 탭 = 후보 다음(orbitTap)
      if (G.selCandIdx === idx0 && G.candidates.length > 1) throw new Error("궤도 탭이 후보 이동 안 함");
    });
    step("input-carried-hold-fallback", () => {
      // 이월 홀드: pressDown을 안 거친 홀드(궤도→전투 전환 등)가 update 폴백으로 브레이크 진입하는지
      startGame(); pressing = true; pressStart = G.t; G.braking = false;
      update(0.05);                                   // held<TAP_MAX → 아직 진입 안 함
      if (G.braking) throw new Error("폴백이 TAP_MAX 전에 브레이크 진입");
      for (let f = 0; f < 12; f++) update(1 / 60);    // held>TAP_MAX 경과
      if (!G.braking) throw new Error("이월 홀드 폴백 미작동(브레이크 미진입)");
      pressing = false; pressUp();
    });
    step("boss-phase2-rush-mid-tele", () => {
      newGame(); startWave(20); const b = G.boss;
      b.atkT = 0; bossSpecial(b, 0.016);             // 차징 시작
      b.hp = b.hpMax * 0.4; updateBoss(0.016);       // 차징 도중 페이즈2 진입
      if (!b.p2Rush) throw new Error("차징 중 페이즈2 진입인데 p2Rush 미설정");
      let g = 0; while (b.tele && g++ < 400) bossSpecial(b, 0.05); // 강화공격 해소
      if (b.atkT > 1.2 + 1e-6) throw new Error("페이즈2 진입 후 강화공격 예고 소실: atkT=" + b.atkT);
      if (b.p2Rush) throw new Error("p2Rush가 1회성 리셋 안 됨(이후 영구 1.2s 광속주기 회귀)");
      // 다음 공격은 정상 주기(bossAtkPeriod)로 복귀해야
      let g2 = 0; while (!b.tele && g2++ < 200) bossSpecial(b, 0.05); // 다음 텔레그래프까지
      while (b.tele && g2++ < 400) bossSpecial(b, 0.05);             // 해소
      if (b.atkT < bossAtkPeriod(b) - 1e-6) throw new Error("p2Rush 후 공격주기가 정상 복귀 안 함: " + b.atkT);
    });

    // ===== 아웃게임(메타) =====
    step("meta-save", () => {
      if (!SAVE || SAVE.v !== 1) throw new Error("SAVE 손상");
      const mods = metaRunMods();
      if (mods.slots !== SAVE.slots || mods.hpMax !== 100 + SAVE.phys.hp * 20) throw new Error("metaRunMods 불일치");
    });
    step("meta-scenes", () => {
      for (const s of ["main", "select", "upgrade", "result", "game"]) { goScene(s); if (scene !== s) throw new Error("goScene 실패:" + s); }
    });
    step("meta-buy", () => {
      SAVE.currency = 9999; const hp0 = SAVE.phys.hp;
      buyPhys(PHYS_LIST.find(p => p.key === "hp"));
      if (SAVE.phys.hp !== hp0 + 1) throw new Error("buyPhys 미작동");
      const sb0 = SAVE.startBoost; buyStartBoost(); if (SAVE.startBoost !== sb0 + 1) throw new Error("buyStartBoost 미작동");
      // 슬롯: 진척조건 미충족 시 구매 불가
      SAVE.slots = 3; SAVE.best.wave = 0; const sl0 = SAVE.slots; buySlot();
      if (SAVE.slots !== sl0) throw new Error("진척조건 없이 슬롯 개방됨");
      SAVE.best.wave = 30; buySlot(); if (SAVE.slots !== 4) throw new Error("조건 충족 후 슬롯 개방 실패");
    });
    step("meta-reward", () => {
      newGame(); G.wave = 12; G.slots[0] = makeCore(3, ["mint", "red"]);
      const cur0 = SAVE.currency; G.ended = false; endGame(false);
      if (scene !== "result" || !lastResult || lastResult.wave !== 12) throw new Error("endGame 정산 실패");
      if (SAVE.currency <= cur0) throw new Error("재화 미적립");
    });
    step("meta-deepweb-lock", () => {
      SAVE.cleared = false;
      if (!chassisLocked(CHASSIS.find(c => c.id === "deepweb"))) throw new Error("미클리어 시 딥웹 잠금이어야");
      SAVE.cleared = true;
      if (chassisLocked(CHASSIS.find(c => c.id === "deepweb"))) throw new Error("클리어 후 딥웹 해제여야");
    });

    // 정상 상태로 리셋 + 보스전 진입(라이브 구동에서 텔레그래프/인바운드탄/요격 렌더 자극)
    step("reset", () => { SAVE.chassis = "legacy"; startGame(); startWave(20); if (G.boss) G.boss.atkT = 0.4; });
  } catch (e) {
    return { ok: false, where: e.where || "?", msg: String(e), log };
  }
  return { ok: true, log };
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--seconds", type=float, default=3.0, help="라이브 구동 시간(초)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    url = INDEX.as_uri()
    console_errors, page_errors = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.on("console", lambda m: console_errors.append(f"[{m.type}] {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        page.goto(url)
        # 게임 부팅 대기: G 정의 + 루프 1회 이상
        page.wait_for_function("typeof SAVE !== 'undefined' && typeof newGame === 'function'", timeout=8000)

        # 신규 코드 경로 강제 구동
        result = page.evaluate(DRIVE_JS)

        # RAF 생존 확인: G.t 가 시간이 지나며 증가해야 한다(렌더 크래시면 멈춤)
        t0 = page.evaluate("G.t")
        time.sleep(args.seconds)
        # 라이브 구동 중 실제 입력도 몇 번 흘려 update/render 경로 자극
        page.keyboard.press("Space")     # 탁(회전 반전)
        page.keyboard.down("Space"); time.sleep(0.4); page.keyboard.up("Space")  # 꾹(브레이크)
        # A키로 Affix 순환(없음→무작위→저주) — 변이 글리프 마커·DDoS 오버레이 렌더 자극
        for _ in range(3):
            page.keyboard.press("KeyA"); time.sleep(0.35)
        page.keyboard.press("Enter")     # 정비 궤도 진입
        time.sleep(0.6)
        t1 = page.evaluate("G.t")

        browser.close()

    # 결과 판정
    print("=" * 56)
    print("NEON KERNEL 검증 결과")
    print("=" * 56)
    drive_ok = result.get("ok")
    for line in result.get("log", []):
        print("  " + line)
    print(f"\nRAF 생존: G.t {t0:.3f} -> {t1:.3f}  ({'OK 증가' if t1 > t0 else 'FAIL 정지!'})")
    print(f"콘솔 에러/경고: {len(console_errors)}")
    for e in console_errors: print("   - " + e)
    print(f"페이지 예외(throw): {len(page_errors)}")
    for e in page_errors: print("   - " + e)

    failed = (not drive_ok) or (t1 <= t0) or console_errors or page_errors
    if not drive_ok:
        print(f"\n드라이브 실패 지점: {result.get('where')} — {result.get('msg')}")
    print("\n" + ("RESULT: FAIL" if failed else "RESULT: PASS"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
