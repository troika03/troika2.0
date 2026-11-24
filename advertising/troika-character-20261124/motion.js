const node = (name) => document.getElementById(name);
const root = node("root");
const { duration, lines, beats } = window.renderCues;
root.dataset.duration = duration;
node("device-rig").innerHTML = deviceMarkup;
const approvalRipple = document.createElement("span");
approvalRipple.className = "approval-ripple";
node("consent-approve").append(approvalRipple);

function fit() {
  root.style.setProperty("--fit", Math.min(innerWidth / 540, innerHeight / 960));
}
fit();
addEventListener("resize", fit);

const tl = gsap.timeline({ paused:true });
window.__timelines = { main:tl };
const camera = node("camera");
const handset = node("handset");
const desktop = node("desktop");
const phoneDevice = node("mobile-app");
const player = node("player");
const island = node("handset-island");
const status = node("island-text");
const mobileState = node("mobile-state");
const final = node("outro");
const waves = [...island.querySelectorAll(".island-wave")];
const musicMeter = [];
for (let i = 0; i < 40; i++) {
  const bar = document.createElement("i");
  musicMeter.push(bar);
  node("meter").append(bar);
}
const anchor = { progress:0 };
tl.to(anchor, { progress:1, duration, ease:"none" }, 0);
gsap.set(handset, { x:37, y:105, scale:.79, rotationY:-15, rotationZ:-12, rotationX:1 });
gsap.set(desktop, { x:-205, y:47, scale:.73, rotationY:25, rotationZ:-5, opacity:0 });
gsap.set(phoneDevice, { opacity:1 });
gsap.set(island, { transformOrigin:"50% 50%" });
gsap.set(node("search-results"), { opacity:0, y:13 });
gsap.set(node("desktop-pointer"), { opacity:0, x:166, y:175 });
gsap.set(node("play-icon"), { opacity:1 });
gsap.set(node("pause-icon"), { opacity:0 });

function toward(element, time, seconds, props, ease="power2.inOut") {
  tl.to(element, { ...props, duration:seconds, ease }, Math.max(0, time));
}
function show(element, time, seconds=.36, y=12) {
  tl.fromTo(element, { opacity:0, y }, { opacity:1, y:0, duration:seconds,
    ease:"power3.out", immediateRender:false }, Math.max(0,time));
}
function leave(element, time, seconds=.28, y=-12) {
  toward(element, time, seconds, { opacity:0, y }, "power2.in");
}
function flash(time, level=.26) {
  toward("#sweep", time-.06, .12, { opacity:level }, "sine.out");
  toward("#sweep", time+.06, .31, { opacity:0 }, "power2.out");
}
function light(time, x, y, opacity=.8) {
  toward("#room", time, 1.0, { x, y, opacity }, "sine.inOut");
  toward("#plinth", time, .86, { x:-x*.45, opacity }, "sine.inOut");
}

const hookReply = lines[1].start;
const pc = lines[2].start;
const pcReply = lines[3].start;
const phone = beats.phone;
const playing = beats.play;
const argument = beats.argument;
const punch = lines.at(-1).start;
const outro = beats.outro;

// Hook: the capsule already listens. The camera comes up as Troika pushes back.
toward(handset, 0, Math.max(.45, hookReply-.24), { x:24, y:81, scale:.86, rotationZ:-6, rotationY:-9 }, "power3.out");
toward(handset, hookReply-.24, .68, { x:8, y:158, scale:1.22, rotationZ:-3, rotationY:6 });
toward(handset, hookReply+.44, Math.max(.3, pc-hookReply-.69), { x:3, y:171, scale:1.25, rotationZ:-1.5, rotationY:1 }, "sine.inOut");
light(hookReply-.2, -26, 23);
leave("#title", hookReply+.25, .38, -26);
flash(hookReply,.19);

// Follow one hand-off from the phone to the already-running Windows desktop.
toward(handset, pc-.22, .68, { x:234, y:100, scale:.73, rotationY:-26, rotationZ:13, opacity:0 });
toward(desktop, pc-.24, .78, { x:1, y:58, scale:.98, rotationY:-8, rotationZ:-2, opacity:1 }, "power3.out");
show("#computer-title", pc+.02, .45);
light(pc-.22, 76, -19);
flash(pc+.20,.24);
show("#consent", beats.consent, .23, 8);
toward("#consent-approve", beats.browser-.23, .12, { scale:.95 }, "power2.out");
tl.fromTo(approvalRipple, { opacity:.95, scale:.46 }, { opacity:0, scale:1.72, duration:.31, ease:"power2.out", immediateRender:false }, beats.browser-.20);
leave("#consent", beats.browser-.02, .25, -8);
show("#desktop-browser", beats.browser, .38, 12);
show("#session-pill", beats.browser+.18, .24, -6);
toward(desktop, beats.browser-.12, .87, { x:0, y:65, scale:1.10, rotationY:2, rotationZ:1 }, "power2.inOut");
toward("#desktop-pointer", beats.browser+.28, .16, { opacity:1 }, "sine.out");
toward("#desktop-pointer", beats.browser+.30, .49, { x:184, y:65 }, "power3.inOut");
show("#search-results", beats.results, .44, 13);
toward("#desktop-pointer", beats.results+.06, .52, { x:250, y:118 }, "power2.inOut");
toward(desktop, pcReply+.72, Math.max(.5, phone-pcReply-.92), { x:-7, y:75, scale:1.13, rotationY:7, rotationZ:2 }, "sine.inOut");

// On the music request the monitor slides away, the phone rolls into frame.
leave("#computer-title", phone-.31);
toward(desktop, phone-.25, .66, { x:-234, y:26, scale:.81, rotationY:23, rotationZ:-9, opacity:0 });
tl.set(handset, { x:187, y:66, scale:.71, rotationY:-19, rotationZ:13, opacity:0 }, phone-.25);
toward(handset, phone-.25, .75, { x:0, y:17, scale:.94, rotationY:7, rotationZ:-4, opacity:1 }, "power3.out");
show("#phone-title", phone+.04, .35);
light(phone-.25, -49, -16);
flash(phone+.09,.28);
leave(phoneDevice, playing-.44, .34, 10);
show(player, playing-.40, .45, 15);
toward("#player-art", playing-.13, .40, { scale:1.06 }, "back.out(1.5)");
toward("#player-art", playing+.27, 1.25, { scale:1, rotation:0 }, "sine.inOut");
toward("#play-icon", playing, .13, { opacity:0 }, "sine.out");
toward("#pause-icon", playing+.04, .16, { opacity:1 }, "sine.out");
toward("#meter", playing-.07, .36, { opacity:.64 }, "power2.out");
flash(playing,.31);
toward(handset, playing-.12, .66, { x:5, y:11, scale:1.02, rotationY:-10, rotationZ:4 });
toward(handset, playing+.54, Math.max(.5, argument-playing-.86), { x:11, y:-3, scale:1.08, rotationY:-5, rotationZ:1 }, "sine.inOut");

// Keep the continuity of the same glass when the player gives way to the argument.
leave("#phone-title", playing-.31, .35, -11);
leave("#meter", argument-.32, .36, 7);
leave(player, argument-.32, .36, -17);
show(phoneDevice, argument-.21, .44, 10);
light(argument-.15, -12, 35);
toward(handset, argument-.20, .66, { x:-10, y:100, scale:1.18, rotationY:5, rotationZ:-4 });
toward(handset, lines[7].start-.18, .56, { x:4, y:11, scale:1.13, rotationY:-5, rotationZ:3 });
toward(handset, lines[8].start-.16, .51, { x:-4, y:112, scale:1.24, rotationY:-3, rotationZ:-2 });
toward(handset, punch-.16, .54, { x:1, y:15, scale:1.25, rotationY:1.8, rotationZ:.3 }, "power3.inOut");
toward(handset, punch+.40, Math.max(.4, outro-punch-.63), { x:0, y:12, scale:1.22, rotationY:0, rotationZ:0 }, "sine.inOut");
flash(punch,.10);

// The smartphone glides behind the mark and leaves the Telegram contact in focus.
toward(handset, outro-.14, .86, { x:146, y:-94, scale:.64, opacity:.32, rotationY:-21, rotationZ:12 }, "power3.inOut");
toward("#vignette", outro-.02, .58, { opacity:.3 }, "sine.out");
toward("#room", outro-.18, 1.2, { x:-37, y:39, scale:1.18, opacity:.71 }, "sine.inOut");
show(final, outro+.09, .60, 22);
tl.fromTo("#outro .outro-mark", { scale:.72, rotation:-13 }, { scale:1, rotation:0,
  duration:.78, ease:"back.out(1.26)", immediateRender:false }, outro+.11);
show("#outro h2", outro+.28, .42, 15);
show("#outro p:not(.channel)", outro+.46, .42, 10);
show("#outro .channel", outro+.68, .40, 9);
toward(final, outro+.76, Math.max(.9,duration-outro-.76), { scale:1.023 }, "sine.inOut");
flash(outro+.12,.18);

const splits = new Map([
  [2, [.92, "Открой браузер", "и найди мне способы заработать денег."]],
  [3, [1.36, "Опять?", "Ты бы хотя бы один прошлый способ попробовал."]],
  [5, [1.60, "Наконец-то задача", "по твоим интеллектуальным возможностям."]],
  [7, [1.12, "Помощник.", "Просто кто-то же должен говорить тебе правду."]],
  [9, [1.22, "Взаимно.", "Чем ещё помочь?"]],
]);
const captionEntries = lines.flatMap((entry, index) => {
  const split = splits.get(index);
  if (!split) return [{ ...entry, index }];
  const [offset, first, second] = split;
  const midpoint = entry.start + offset;
  return [
    { ...entry, index, end:midpoint, text:first },
    { ...entry, index, start:midpoint, text:second },
  ];
});
for (const [captionIndex, entry] of captionEntries.entries()) {
  const { index } = entry;
  const cue = document.createElement("article");
  const role = document.createElement("p");
  const copy = document.createElement("p");
  const isTroika = entry.speaker === "troika";
  cue.className = "cue" + (isTroika ? " cue-troika" : "") + (index >= 8 ? " cue-hit" : "");
  role.className = "cue-role";
  role.textContent = isTroika ? "ТРОЙКА" : "ТЫ";
  copy.className = "cue-text";
  copy.textContent = entry.text;
  cue.append(role, copy);
  node("subtitles").append(cue);
  if (index === 0) gsap.set(cue,{ opacity:1 });
  else show(cue, entry.start, .14, 7);
  const end = captionEntries[captionIndex+1]?.start || outro;
  leave(cue, Math.min(end-.125, entry.end+.20), .125, -5);
}

const browseText = "Как заработать деньги";
let currentStatus = "";
function wavePath(t, amp, frequency, offset) {
  const coords = [];
  for (let i=0;i<=28;i++) {
    const u=i/28;
    const y=15+Math.sin(u*frequency*Math.PI*2+t*8+offset)*Math.sin(u*Math.PI)*amp;
    coords.push((i ? "L" : "M")+(44*u).toFixed(1)+" "+y.toFixed(2));
  }
  return coords.join(" ");
}
function detail(t) {
  const line = lines.find(l => t >= l.start && t <= l.end);
  const answering = line?.speaker === "troika";
  const strength = line ? (window.voiceEnvelope?.[Math.round(t*30)] ?? .26) : .02;
  const nowPlaying = t >= playing && t < argument-.2;
  const nextStatus = answering ? "Отвечаю…" : line ? "Слушаю…" : nowPlaying ? "Музыка играет" : "Слушаю…";
  if (nextStatus !== currentStatus) {
    status.textContent = nextStatus;
    mobileState.textContent = answering ? "Отвечаю" : "Слушаю";
    mobileState.style.color = answering ? "#8cf0c4" : "#f4f5f7";
    currentStatus = nextStatus;
  }
  waves.forEach((path,index) => path.setAttribute("d",wavePath(t, (.9+strength*(answering?8.4:6.3))*(1-.16*index),[1.6,1.1,2.4][index],[0,1.2,2.5][index])));
  node("mobile-orb").style.transform = "scale("+(1+strength*(answering?.052:.020))+")";
  node("mobile-orb").style.filter = answering ? "drop-shadow(0 0 "+(5+strength*13)+"px #3ddc974c)" : "";
  node("float").style.transform = "translate("+(Math.sin(t*.92)*2.2)+"px,"+(Math.sin(t*.81)*3.2)+"px)";
  const typed = Math.min(1,Math.max(0,(t-beats.query)/Math.max(.2,beats.results-beats.query-.14)));
  node("browser-query").textContent = browseText.slice(0,Math.ceil(typed*browseText.length));
  const played = Math.max(0,t-playing);
  node("seek-fill").style.transform = "scaleX("+Math.min(.98,(14+played)/166)+")";
  node("player-time").textContent = "0:"+String(14+Math.floor(played)).padStart(2,"0");
  musicMeter.forEach((bar,i) => {
    const amplitude = .12 + .88 * (Math.sin(t*20+i*.88)**2) * (Math.sin(i*.73+t*4)**2);
    bar.style.transform = "scaleY("+amplitude.toFixed(3)+")";
  });
}
window.seekFrame = time => {
  tl.seek(time,false);
  detail(time);
};
window.seekFrame(0);
