# Project NEON KERNEL — 작업 인계 문서

원버튼 모바일 로그라이트 슈팅 게임. 기체가 화면 중앙 고정, 6궤도 슬롯이 자동 회전·연사,
탁(회전반전)·꾹(브레이크) 단일 터치 조작. 텍스트 제로 네온 UI.

## 파일 위치
- **프로토타입(메인 작업물)**: `prototype/index.html` — 단일 HTML+Canvas, 의존성 0
- **게임 정의서(설계 마스터)**: `docs/NEON_KERNEL_정의서_최종판.md` — 모든 설계 결정의 근거
- **미리보기 서버**: `.claude/launch.json`의 `prototype` (python http.server 포트 4321)
  - node/npx 없으면 python 사용. `python -m http.server 4321 --directory prototype` 로도 실행 가능

## 검증 방식 (중요)
- 코드는 거의 전부 **eval 하네스로 게임 엔진에서 직접 측정/검증**하며 작업했다.
- **교훈: eval 검증 시 `update()`만 말고 `render()`도 매 프레임 돌려야 함** (렌더 크래시는 update-only 테스트로 안 잡힘 — 실제 RAF 정지 버그를 그렇게 놓친 적 있음).
- 미리보기(Claude Preview/브라우저)로 화면 확인 + 콘솔 에러 0 확인이 기본 루프.

### 자동 검증 하네스 (Playwright) — 코드 수정 후 필수 실행
- **`python tools/verify_game.py`** — 실제 Chromium으로 `prototype/index.html`을 띄워 자동 점검.
  - 이 환경엔 **node가 없어** JS Playwright 대신 **Python Playwright**를 쓴다(`pip install playwright` + `python -m playwright install chromium` 1회 설치 완료됨).
  - 점검 항목: ①콘솔 에러/경고 ②페이지 예외(throw) ③**RAF 생존**(`G.t` 증가 — 렌더 크래시면 RAF가 멈춰 G.t 정지 → 자동 검출. 위 교훈을 자동화).
  - 신규/주요 코드 경로(기체 5종 전환·압축 훅·딥웹 룰렛 3분기·저주 슬롯잠금·신규 렌더 분기)를 합성으로 강제 구동 후 라이브 입력까지 흘린다.
  - 종료코드 0=PASS / 1=FAIL. 옵션: `--headed`(창 표시), `--seconds N`(라이브 구동 시간).
  - **새 시스템 추가 시 `DRIVE_JS`에 그 경로 step을 추가**해 회귀 커버리지를 늘릴 것.
  - ⚠️ 구문 오류는 스크립트 전체 파싱을 죽여 게임이 백지가 된다(과거 `applyChassisToCore({...})` 닫는 `)` 누락 사례). 이 하네스가 그런 류를 즉시 잡는다.

## 씬 구조 (아웃게임 ↔ 인게임)
- **로드 시 `scene='main'`(아웃게임)으로 시작** — 더 이상 인게임이 곧바로 안 뜬다. `goScene`로 전환.
  씬: `main`/`select`/`upgrade`/`game`/`result`. `loop`가 game이면 `update+render`, 아니면 `renderMeta`.
- **G는 `startGame()`(=newGame+game씬) 때 생성** — 메타 화면에선 `G`가 undefined일 수 있다(메타 렌더는 `SAVE`만 참조).
  ⚠️ 검증/스크린샷 하네스는 `SAVE` 존재로 대기하고, 인게임 경로는 `startGame()`/`newGame()` 먼저 호출해야 함.
  (eval_balance가 `G` 대기로 남아 8s 타임아웃으로 죽어 있었음 — 2026-06 수정. 새 하네스는 반드시 SAVE 대기.)
- ⚠️ **입력 버그는 함수 직접호출 테스트로 못 잡는다** — `reviveRun()` 직접 호출은 통과해도 실제 탭(pressDown→pressUp)이
  막혀 있던 사례(이어하기 입력 불능). UX 경로는 verify의 `input-*` 스텝처럼 **pressDown/pressUp 체인 경유**로 검증할 것.
- **메뉴 조작 = 터치/클릭 버튼**(`metaButtons` 히트테스트). 키보드 테스트키는 `game` 씬에서만 동작.

## 조작 / 테스트 키
- **PC**: 마우스 클릭(또는 Space) — 짧게=탁(회전반전), 길게=꾹(브레이크/흡수확정). **(game 씬 한정)**
- **모바일**: 터치
- `R` 재시작 · `H` 안내토글
- `Enter` 정비궤도(합성) 즉시 진입 · `C` 후보 재추첨
- `B` 코어 시험장 토글 → `1~8` / `[ ]` T1 8종 코어 전환 (무적, 더미 스폰)
- `L` 해금 슬롯 수 3~6 순환 (아웃게임 슬롯 게이팅 시뮬레이션)

## 구현 완료 시스템
### 전투 코어 (검증·승인됨)
- 6궤도 자동회전·자동연사, 탁=회전반전, 꾹=브레이크(6방향 고정사격+과열드레인 1→3→5%)
- **브레이크 즉발**(2026-06): `pressDown`이 누르는 순간 `G.braking=true`(회전 즉시 정지 — 기존 TAP_MAX 0.18s 대기 제거).
  탁/꾹 분류는 release의 `held<TAP_MAX`. **드레인 게이트 = 이번 누름 지속시간**(`pressing?(G.t-pressStart):∞`)`>TAP_MAX`
  (누적 brakeTime 아님 — grace 재진입 탭처럼 brakeTime이 이월돼도 탁 플릭은 항상 무비용 = "탭=회전반전" 직관 유지).
  드레인 **단계**(1→3→5%)는 brakeTime 기준. 탭스팸은 방향 반전이 자체 패널티. `update()`에 이월 홀드용 폴백 진입 잔존. `didBrake` 제거.
  verify: `input-brake-instant`/`input-brake-drain-gate`/`input-grace-tap-free`/`input-carried-hold-fallback`.
- 오버히트 노바(과부하 후 떼는 순간 360도 충격파), 0.5초 무적, 체력 0~100 3구간 네온
- 360도 예고글로우→적 스폰, 적 4종(러너/바운서/슈터/실더), 예산 기반 웨이브, 투사체 상쇄
- 적 체력 웨이브 스케일링 `hpScale(w)`: 섹터1 ×1.0 → 섹터2 ×1.07~1.65 → 섹터3 ×1.8~3.0

### 코어/합성 (3티어 체계, 정의서 3·4·5·6장)
- **모델**: ATTR 4색(mint/red/purple/grey) + 코어는 `{tier, colors, behavior, bparams, ...}`.
  T1=`makeT1(spec)`, T2=`makeT2(spec)`, T3=`makeCore(3,colors,base,mat)`.
- **T1 8종**(`T1_CORES`, 정의서 6.1): straight/scatter/dot/area/pull/delay/knockback/fragment.
  거동별 탄 렌더 + 코어 실루엣(`drawCoreShape`)으로 시각 구분.
- **T2 12종**(`T2_CORES`+`T2_LOOKUP`, 정의서 6.2): 두 T1 서브타입 조합으로 룩업(순서무관).
  신규 거동: burst/beam/hold/bounce/shed. 융합 3종이 "부모 능력 결합".
- **T3 색조합 10종 효과**(`COMBO_FX`, 정의서 6.3): coreMod(동색 오버클록)/onHit(이종 합선).
  상태: `e.vuln`(장갑파괴), `e.held`(홀딩).
- **압축 알고리즘** `resolveCompression`/`canCompress`(정의서 3.3): T1+T1 동색→T2,
  T2+T2 색무관→T3, 반시계 베이스, 연쇄, 1수 앞보기 예외, 만석 덮어쓰기. 8케이스 eval 검증.
  단계 큐 애니메이션(`planCompression`→`updateMerge` slide→pop→pause)으로 합쳐지는 과정 표시.
- **혈통 글리프**(`drawCoreGlyph`): T1=단일형태 / T2=육각프레임+부모2형태 위성 / T3=회전아우라+듀얼색+부모위성.

### 정비 궤도 (보상, 정의서 3장)
- 페이즈 `combat`/`orbit`. 웨이브 클리어→정비궤도.
- **2단계 이산 선택**(회전정지): ①후보(탁=다음, 꾹=확정) → ②코어=슬롯선택/스탯강화=대상코어선택.
  (정의서 3.2 연속회전 역흡수는 폐기—정밀선택에 부적합. 이산선택으로 대체.)
- **유형 A/B**(정의서 3.5): A=완제품 코어, B=스탯 오버클록(`BOOSTS` 4종). 비율 섹터1 80:20→섹터3 40:60.
- **슬롯 게이팅**: `MAXSLOTS`/`G.maxSlots`(3~6). 해금순서 `SLOT_UNLOCK_ORDER=[0,2,4,1,3,5]`
  → 3슬롯=삼각형(0·2·4) 360도 균등. `cwOf`/`ccwOf`가 잠긴슬롯 건너뜀(삼각형도 압축 가능).
  슬롯이 T3 개수 통제(3슬롯=T3 1개, 6슬롯=2~3개).

### 기체 (하드웨어 필터, 정의서 8장) — 검증·완료
- **모델**: `CHASSIS` 5종(레거시/프록시/광랜/글리치/딥웹). 코어 로직 비침습 — `applyChassisToCore`가
  코어의 `_baseStats` 보존 후 기체 `applyCore`로 물리 파라미터만 왜곡. `makeCore/makeT1/makeT2` 모두 통과.
- **거동 데미지 채널도 스케일**: 기체 `dmg` 배율을 `DMG_BPARAMS`(dotDps/puddleDps/beamDmgps/holdDps/
  burstDmg/fragDmg)에도 적용(유틸=반경·힘·시간 제외). beam(`base.dmg=0`)은 probe로 배율 산출. → 거동딜 코어도
  "같은 코어 다른 기체"가 작동(eval: 변동폭 ≈1.0→1.9~4.2). bparam 스케일 안 하면 beam/dot/hold가 기체 무관해짐.
- **기체 훅**: `onCompressionSuccess`(applyMergeStep에서 호출) — 광랜=연사 복리 스택+`reapplyChassisToAllCores`,
  딥웹=`rollDeepweb`(대박20/중간50/저주30, 저주=`cursed` 플래그→`canCompress` 차단=슬롯 일시잠금).
  프록시=`absorbDamage`(보호막)+`brakeDrain`0, 글리치=`suppressFiring`(과열 정지)+과열→노바 전환.
- **시각**: 프록시 보호막 링 / 글리치 과열 플리커 / 딥웹 저주(붉은X)·대박(금빛) 마커.
- **테스트 키**: `Q`/`E` 순환, `1~5` 직접 선택(런 중 전환은 디버그용). 정식 선택은 아웃게임 예정.
- ⚠️ 딥웹 룰렛 대박/저주는 현재 스탯 잭팟/디버프 임시구현 — 정식은 Affix(6.4) 연동 필요.

### Affix 모듈 (변이 코어, 정의서 6.4) — MVP 완료
- **모델**: `AFFIXES`(접두5·접미5·마이너스2), `core.affixes={prefix,suffix}`. 합성 순서 **base→Affix→기체**(멱등).
  `applyAffixesToBase`(stat 변형)가 기체 앞 레이어. `computeAffixFx`→`core.affixFx`(온히트/렌더 플래그).
- **접두(형태)**: 거대한/궤도의/다중의/관통의/분열의. **'유도의'(homing)는 폐기**(유도 미사용 확정과 충돌, 다중의로 대체).
- **접미(효과)**: 치명적인/가속의/과부하/포맷팅(`e.vuln` 재사용)/흡수의. **마이너스**: 디도스(시야가림)/랜섬웨어(스탯디버프).
- **온히트 배선**: `fireSlot`이 `affixFx`를 탄에 전파(`tagAffix`)→`collide`에서 crit/vulnOnHit/affixFrag/lifesteal 처리.
  dmg 총배율(Affix×기체)이 거동채널(bparams)에도 적용 — beam(base.dmg=0)은 probe 경로.
- **획득 = 유형C 모듈 보상**(사용자 확정, 정의서 6.4 '모듈' 프레임): 정비궤도 후보에 모듈 등장 → 대상 코어 선택(유형B 흐름 재사용)
  → `addAffix`로 단일 슬롯 부착. **변이코어 통째 드롭은 딥웹/제로데이 전용**. 마이너스 affix는 모듈 보상 제외(딥웹 저주 전용).
- **T3 한정**(사용자 확정): 등장 조건 = **T3 코어 장착 중**(`hasT3`, 22%), 부착 대상 = **T3 코어만**(`affixableSlots`).
  T3 천장 이후 강화 영역(정의서 3.3/6.3). `stepSlots`가 pickedAffix면 T3목록 반환 → 렌더·탁·확정 일관.
- **모듈 명칭 = 형태(접두)/효과(접미)**(사용자 확정): 라벨에 'Affix' 대신 `형태`·`효과`(정의서 6.4 분류, 위치 아닌 기능 전달).
  `rollCandidates`/`orbitConfirm`/`drawAffixModuleIcon`/`candInfo`.
- **시각**: 변이 글리프 마커(금빛/붉은 헤일로+접두/접미 핍), DDoS 화면 오버레이. **테스트키 `A`**=장착코어 Affix 순환.
- ⚠️ MVP라 정식 풀(10+10)은 미완. 필드 드롭/LV4 해금 미구현(현재 웨이브 게이트). 딥웹 연동 미배선(아래 참조).
- **밸런스 발견**(eval_balance.py): 다중의(strands+2)가 1가닥 직격코어를 ×3.0(콤보 ×3.85) — 아웃라이어, 15장 패스 1순위.
  거동의존(다중의 on beam=무효), 유틸affix(궤도의/관통의/흡수의)=단일표적 0DPS.

### SF 알림 (텍스트리스 재해석)
- "텍스트리스 = 긴 설명 지양이지 이름 은닉 아님"(사용자 확정). **이름만** 짧게(설명문 X), 기체 위 칩(이름+거동 글리프).
- **조준 팝업(`G.aimToast`, 지속)**: 정비궤도 cand 단계에서 **조준선이 향한 보상의 이름 + 한 줄 효과**(사용자 확정 — 부착 시가 아닌 조준 시).
  `rollCandidates`/`orbitTap`에서 `setAimToast`, 단계 전환/`finishMerge`에서 `clearAimToast`. `candInfo`가 코어/모듈/강화 → 이름·거동·색·desc.
  **설명 한 줄(desc)**: 코어=`core.fx`(거동 설명), Affix=`AFFIX.desc`(효과), 강화=`BOOST.desc`(수치). "이름만으론 성능 파악 어려움" 해소.
- **일시 토스트(`pushToast`/`G.toasts`)**: 조준으로 안 보이는 **합성 결과**(`applyMergeStep`)만. 글리치 인→홀드→페이드(~1.6초).
- 렌더 `drawToasts`(조준+일시 통합, `drawToastChip`). 획득/부착 시점 토스트는 제거(조준 팝업으로 대체).

### 아웃게임 (메타, 정의서 9장) — 풀 1차 완료
- **영속 `SAVE`(localStorage `neonkernel_save_v1`)**: 재화·슬롯(3~6)·피지컬레벨·시작부스트·기체·클리어여부·최고기록. `persist()`로 저장.
- **메인 화면**: 네온 로고 + 누적 재화 + `시작`/`기체 선택`/`강화` + 최고기록.
- **기체 선택**: 5기체 카드(아이콘·특성·선택/잠금). `chassisLocked`=딥웹은 `SAVE.cleared` 선행(8.2). 선택 시 `SAVE.chassis`.
- **강화(9.4)**: ①`SLOT_STEPS` 슬롯개방(재화+`best.wave` 진척조건) ②`PHYS_LIST` 4종(rot/hp/intercept/brake) ③`STARTBOOST`. `buySlot/buyPhys/buyStartBoost`.
- **정산(9.3)**: `endGame(cleared)` — 재화=웨이브×3+섹터보너스(10/20/30)+첫도달(신기록 점프)+T3×10. 최고기록 갱신.
- **인게임 연동 `metaRunMods()`**(newGame이 호출): `maxSlots`/`hpMax`/`rotMul`/`brakeMul`/`novaMul`/`interceptBonus`/`startCores`.
  적용 지점 — 회전 `rotMul`, 드레인 `brakeMul`, 노바 `novaMul`, hp클램프 `G.hpMax`, 브레이크관통 `interceptBonus`, 시작코어 수.
- **전환**: 사망(`die`→1.8s 또는 탭)·30방 클리어 → `endGame` → `result` 씬. `startGame`이 `SAVE.chassis`로 `currentChassisIndex` 설정.
- **이어하기(9.5) — 완료**: 보스전 사망 1회 한정 부활. `die()`가 `G.boss && !G.continueUsed`면 `G.reviveOffer={t,dur:6}`,
  오퍼 중 탭=`reviveRun()`(HP 50%·빌드/보스 페이즈 유지·1.6s 무적·잔여 적탄 정리), 시간초과=정산. 일반 웨이브 사망엔 미적용(9.5 의도).
  프로토타입 트리거=탭(정식은 광고/유료, 14장). 사망 오버레이에 시안 카운트다운 링+▶글리프. verify: `revive-boss-offer`/`revive-nonboss-skip`.
- **사망 중 입력은 `pressDown`에서 처리**(2026-06 수정): 기존 `pressDown`이 `G.dead`면 무조건 return → pressing이 안 서서
  pressUp의 탭 분기가 **도달 불가**(이어하기/정산스킵 입력 불능 버그, 함수 직접호출 테스트는 통과해 못 잡았음). 현재:
  `deadT<0.5` 연타 무시(1회 부활 오발동 보호) → 오퍼면 `reviveRun()` / 아니면 `endGame(false)`. 사망 중 release는 무동작.
  **사망 중에도 `G.t`·`updateFx`(파티클/셰이크/플래시) 진행** — 사망 폭발·부활 링 펄스 동결 버그 수정. verify: `input-revive-chain`.
- ⚠️ 미구현: 링크 배치학(9.2). (이어하기·슈퍼 정비궤도·보스 3종은 완료) intercept/brake 강화 밸런스 미측정.

### 보스 3종 (정의서 11.1 / 3.7) — 완료 (시그니처 텔레그래프 패턴 포함)
- **모델**: `BOSS_WAVES`(10/20/30)·`BOSS_DEF`. `G.boss`(hp·hpMax·phase·`atkT`·`tele`·기믹상태). `startWave`가 보스화(예산0), 처치=클리어.
  `update`에 `updateBoss`(+`bossSpecial`)/`collideBoss`, `render`에 `drawBoss`(+`drawBossTele`). 웨이브 클리어 게이트에 `!G.boss`.
- **WALL_E**(10): 공전 + 3 회전방패 호(`walleBlocks` 접근각 차단). **신패턴: 집속 일제사** — 보스→중심 조준 예고→수렴 탄류(공전으로 각도 매번 변함=재정렬). → 슈퍼 정비궤도.
- **ANTI_V**(20): 상단 부유, 포탑 스폰 + 조준방향 에러블록(`b.blocks`). **신패턴: 멀티 락온** — K방향 동시 예고→동시 인바운드(p1 K=3/p2 K=4). → 슈퍼 정비궤도.
- **KERNEL_PANIC**(30): `bossBorderR()` 테두리=HP, 4속성 무제한 물량. **신패턴: 수축 링** — 테두리 예고→틈 있는 전방위 인바운드(p1 틈2/p2 틈1·고속). 처치=`endGame(true)`.
- **시그니처 공격 = 정렬 보상형 텔레그래프**(2026-06 확정): 예고글로우 후 **중심 인바운드 탄**(`mkInbound`, `boss:true`) → 브레이크 6방향 고정사격(2.1)이 그 각도를
  자동 요격(기존 상쇄 로직 재사용, 새 충돌코드 0). "탁으로 위상 맞춰→꾹으로 요격" 루프. 슬롯 수↓=격자 성김=난도↑.
- **텔레그래프 기하**(2026-06 보정): 스폰 반경 `bossTeleR()`=min(W,H)×0.45 **화면 비례**, 탄속=거리/도달시간(해상도 무관 방어 시간창).
  WALL_E 예고각=**보스의 극각**(`atan2(b.y-CY, b.x-CX)` — 기존 보스→중심 방향을 극각으로 오용해 **반대편 스폰**되던 버그 수정).
  ANTI_V 락온 간격 **60°의 배수**(p1 120°/p2 60°×4 부채꼴) — 90°는 6슬롯 격자와 비호환이라 정렬 완벽해도 피탄(11.2 노히트 위반)이어서 수정.
  **보스별 대응 차별화**(eval 실측): walle/antiv=정렬 요격(시그 도달 0), panic 수축링=**스윕 유지**가 정답(브레이크 시 격자 동결로 틈새 통과 — 의도된 변주).
- **페이즈2**(50% HP): 기믹 강화 + 공격주기 `bossAtkPeriod`×0.62 + 진입 직후 강화공격 예고(차징 중 진입 시 `p2Rush` 플래그로 해소 후 1.2s 보장).
  **노바가 보스에도 큰 피해**(`fireNova`, 8.1, 방패무시).
- **슈퍼 정비궤도**(3.7): 중간 보스 처치 → `enterOrbit(true)` → 후보 6개·`orbitPicksLeft`=2 연속 픽.
- **HP 밸런스**(`python tools/eval_boss.py` 실측, 레거시·결정적 빌드): PANIC 2600(스윕 17s), ANTI_V 351(28~30s),
  WALL_E 85+틈확대(ARC 0.7, **정렬 강제** — 3슬롯 자동스윕 격파 불가, 정렬 봇 19.9s).
- **eval_boss 정렬(리듬) 모드 + 시그니처 추적**(2026-06): 스윕 봇 외에 "방향형 예고만 정렬+브레이크 1.9s, 평소 스윕" 봇 추가.
  보스탄(boss:true) 개별 추적으로 **도달/요격 분리** — walle 24/38→정렬 0/11, antiv→정렬 0/22, panic 스윕 0/82(노히트 수치 성립).
  ⚠ 정렬 봇의 TTK/총피해는 미니언 통제 못하는 봇 한계 포함(antiv 참고치). 드레인은 `chassis.brakeDrain=()=>0` 패치로 제거
  (**`G.brakeMul=0`은 `|| 1` falsy 함정으로 무효** — 주의).
- ⚠️ 보스 정밀 패턴 추가 여지(3페이즈·고유 탄막)는 후속.

### 화면비 정규화 (2026-07 — 모바일 세로/태블릿 가로, "B+속도 하이브리드")
- **문제**: 중앙고정 360° 위협 모델이 정사각 화면 가정 — 폰 세로(390×844)에서 좌우 반응시간이 상하의 **1/2.16**,
  예고 글로우 **66% 방향이 화면 밖**(`max(W,H)` 기준 원형 스폰), 후보 궤도(200px) 좌우 클립.
- **모델**(사용자 확정): 스폰=타원(화면경계+`spawnMargin`) + **모든 방사형 속도를 `velScale(θ)=clamp(edgeDist(θ)/reactRef, lo, hi)`로 스케일**.
  반응시간 = edge/(base·edge/Rref) = **Rref/base = 방향·기기 무관 상수**. "정사각 게임을 화면에 늘리되 원은 원으로, 속도만 보정".
- **적용 지점**: `doSpawn`(타원+`e.vmul`), 적 이동(`espd×vmul`), 슈터 탄·정지거리(260→`edgeDist×0.7` 클램프),
  **플레이어 탄속·빔 사거리·delay 탄**(`fireSlot`의 `vs` — 사용자 확정: 장사거리 탄도 스케일=요격 타이밍 균일),
  예고 글로우(경계-22px 타원), 후보 궤도(타원 클램프 `min(candidateR, W/2-28, H/2-28)`, flyIn 동일), 바운서 궤도(`min(W,H)×0.4`).
  보스 텔레그래프는 기존 `bossTeleR`(거리/도달시간)로 이미 정규화 — velScale 미적용(이중 보정 금지).
- **캘리브레이션**(`python tools/eval_aspect.py` 실측): `reactRef=430`(러너 80px/s → 균일 5.4s = 구 데스크톱 밴드
  5.0~7.1s 중하단, 승인 조작감 보존), clamp `[0.5, 1.5]`. 결과: 방향 격차 폰 **2.16×→1.24×**(clampLo binding 잔여),
  태블릿 가로·정사각 **1.00~1.03×**, 기기 밴드 3.95~5.03s 수렴(폰-태블릿 패리티). 보스 TTK·기체 배율 회귀 없음(±0.3s).
- **방향 정책**(사용자 확정): 폰=세로 전용, 태블릿=가로 전용. `edgeDist`가 방향 무관 자동 대응이라 코드 분기 0 —
  실제 orientation 강제는 배포 단계(안드로이드 매니페스트) 몫. verify: `aspect-*` 4스텝, 샷: `Bm2/Bm4`.

### 렌더 성능 (2026-06 — Chrome 렉 해결)
- **병목 = Canvas2D `shadowBlur`**(네온 글로우). 드로우마다 GPU 블러 패스 강제 → 헤드드 실측 과밀 전투에서
  52fps·**최대 217ms 스톨** vs shadowBlur 끄면 **60fps 고정·17ms**. 95% 드로우가 블러였음(127/134).
  ⚠ **블러 반경 축소는 무효**(Chrome 섀도 경로는 반경 무관 고정 오버헤드) — 오직 `shadowBlur=0`만 효과.
- **해결**: 전역 `glowMul` 스케일러(ctx.shadowBlur setter 오버라이드, 1곳) — 핫 루프(적탄·적·아군탄·파티클)에서
  `glowMul=0`으로 블러 끄고 **싼 가산 헤일로**(`neonGlow`, lighter 1패스 큰 반투명 원)로 대체. 소수 히어로 FX
  (보스·노바·충격파·예고·UI 링·빔)만 블러 유지. **DPR 상한 2→1.5**(대형 화면 백킹스토어 픽셀 억제).
  파티클 상한 300(다중 폭발 누적). → 4.2M px, 중앙값 60fps 고정. 시각: 가산 블룸으로 룩 보존(오히려 깔끔).
- ⚠ 렌더 핫 루프에 `shadowBlur` 직접 지정 금지 — `glowMul=0` 구간이면 무효, 글로우는 `neonGlow`로.
- **잔렉 2차 패스**(2026-07): 스톨 프레임 실측 JS 0.2~0.5ms → 원인은 컴포지터/DOM. ①`getContext('2d',{alpha:false,
  desynchronized:true})` + 배경 그라데이션을 CSS→캔버스 내부(`paintBg`/`bgGrad`, clearRect 대체)로 = 페이지 블렌딩 제거
  ②`setHud()` — HUD DOM 쓰기 변경시+최대 5Hz 스로틀(매 프레임 textContent가 레이아웃 강제)
  ③예고 글로우·장판 blur 제거(웨이브 스폰 리듬 잔렉 원인 — 예고는 가산 헤일로 2패스) ④`loop()` dt 중앙값(5프레임)×1.3
  클램프 — 산발 프레임 드랍 시 오브젝트 점프 억제(지속 저fps엔 5프레임 내 적응). → 자연 웨이브 w24 실측 slow 0/472·max 16.9ms.
- ⚠ `hud.textContent` 직접 쓰기 금지(setHud 경유 — hudLast 캐시 어긋남), 배경은 clearRect 아닌 `paintBg()`(불투명 캔버스).

### 코어 시험장 (`B` 키)
- T1 8종을 슬롯에 전부 장착해 손맛 비교. 무적, 더미 스폰.

## 밸런스 기준선 (회귀 주의)
- 전투 발사간격/적HP/위상정렬: "조작감 꽤 괜찮다" 승인됨(함부로 회귀 금지).
- T2 12종 단일DPS 밴드 7~22. T1 2~10, T3 15~91. "의도된 불균형"(정의서 8장) 내 역할 유지.
- 정밀 수치는 정의서 15장 8번 밸런싱 패스에서 일괄(현재는 CFG/TIER_STATS 상수로 분리).
- **기체별 평균 화력 배율**(레거시=1.00, `python tools/eval_balance.py`): 프록시 1.00(raw·실효↑) /
  광랜 0.69(단발↓·물량↑) / 글리치 0.57(평소 약함=노바 연료, 의도) / 딥웹 1.10(+룰렛 변동).
- ⚠️ **미해결 아웃라이어**: 브로드캐스트(T2 scatter) effDPS 56~62 → 기준선 7~22 크게 이탈.
  15장 밸런싱 패스 후보(지금 손대면 회귀 위험).

## 설계 확정 사항
- **T4 미추가**: T3가 천장(정의서 6.3). 후반 깊이 = 슬롯이 T3개수 통제 + 유형B 스탯펌핑 + Affix(6.4) + 기체.
- **유도(homing) 미사용**: 위상정렬 조준스킬과 충돌(사용자 결정). T1엔 원래 없음.
- 슬롯은 아웃게임 고정(런 내 미개방) → 아웃게임 성장·반복 게이트 보존.
- **기체 dmg 배율은 거동 데미지 채널(bparams)에도 적용**(2026-06 확정): 안 그러면 beam/dot/hold 코어가
  기체 무관해져 정의서 8장 "같은 코어 다른 기체" 정체성이 깨짐. 유틸 파라미터(반경·힘·시간)는 미스케일.
- **화면비 대응 = B+속도 하이브리드**(2026-07 확정): 레터박스(A) 대신 타원 스폰+전 방사속도 `velScale` 보정.
  장사거리 탄 포함 **예외 없이** 스케일(요격 타이밍 균일이 이유 — 사거리 임계 없는 단일 규칙). 폰=세로/태블릿=가로 전용.
- **딥웹 대박 = Affix '품질 잡팟'**(2026-06 확정, 미배선): 가치를 "접근(access)"이 아닌 "품질/물량"으로 걸어야
  Affix 해금 후에도 의미 유지. 대박=필드보다 좋은 Affix(이중=글리치에러코어 비중↑·고굴림), 헤드라인은 제로데이(해금무관).
  → 딥웹 룰렛(현 스탯 임시구현)에 Affix 배선 시 이 방향으로. (Affix `setAffixes(core,'random'|'curse')` 재사용)

## 다음 작업 후보 (미정)
1. 고밀도·정예 적 가독성 (섹터3, 위상왜곡자·하드웨어크러셔)
2. 보스 심화 (3페이즈·고유 탄막 확장 · 정밀 HP/위협 곡선) — 3종 + 시그니처 텔레그래프 + 이어하기는 완료
3. Affix 확장 (정식 풀 10+10 + 필드 드롭/LV4 해금 + 딥웹 '품질 잡팟' 배선) — MVP는 완료
4. 아웃게임 잔여 (링크 배치학 9.2) — 풀 1차·슈퍼 정비궤도·이어하기(9.5)는 완료
5. 밸런싱 패스 (정의서 15장) — 브로드캐스트·다중의 아웃라이어, intercept/brake·보스 HP 곡선 일괄

## 작업 스타일 (사용자)
- 시스템 간 모순을 날카롭게 잡음. 결정 전 장단점·대안을 솔직히 제시하고, 사용자 확정 후 구현.
- 한 번에 하나씩 확정. 데이터/eval로 근거를 보이는 걸 선호.
