import * as T from 'three';
import {Beat} from './beats';
import {assistant, box, boxGeometry, diode, person, phone, pivot, solid} from './models';

const WIDTH = 1080;
const HEIGHT = 1920;
const V = (x: number, y: number, z: number) => new T.Vector3(x, y, z);
const cap = (x: number) => Math.max(0, Math.min(1, x));
const pace = (v: number) => {
  const t = cap(v);
  return t * t * (3 - 2 * t);
};
const blink = (t: number, at: number, span = 0.092) =>
  1 - (1 - Math.max(0, 1 - Math.abs(t - at) / span)) ** 2;

function paintTexture(width: number, height: number, draw: (ctx: CanvasRenderingContext2D) => void) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext('2d')!);
  const tex = new T.CanvasTexture(canvas);
  tex.colorSpace = T.SRGBColorSpace;
  return tex;
}

function terminal() {
  return paintTexture(1008, 966, (ctx) => {
    const gradient = ctx.createLinearGradient(0, 0, 0, 960);
    gradient.addColorStop(0, '#080d23');
    gradient.addColorStop(0.55, '#111729');
    gradient.addColorStop(1, '#141c31');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 1008, 966);
    ctx.strokeStyle = '#253355';
    ctx.lineWidth = 2;
    ctx.strokeRect(42, 64, 922, 822);
    ctx.fillStyle = '#172037';
    ctx.fillRect(43, 65, 920, 46);
    ctx.fillStyle = '#7783a9';
    ctx.font = 'bold 19px Consolas, monospace';
    ctx.fillText('troika / voice', 67, 94);
    ctx.fillStyle = '#b68250';
    ctx.fillRect(871, 84, 8, 8);
    ctx.fillStyle = '#508b91';
    ctx.fillRect(896, 84, 8, 8);
    ctx.fillStyle = '#698872';
    ctx.fillRect(921, 84, 8, 8);
    ctx.fillStyle = '#1b283c';
    ctx.fillRect(570, 112, 1.5, 773);
    const words = [
      'voice.input       :: listening', 'local.action      :: flashlight',
      'transcript        :: ready', 'search.sources    :: verified',
      'microsoft.support :: screen recording', 'workspace         :: document',
      'generate.slides   :: pending', 'export.pptx       :: local file',
      'windows.client    :: connected', 'android.client    :: connected',
      'voice.output      :: complete', 'session           :: waiting',
    ];
    for (let i = 0; i < 30; i++) {
      const y = 143 + i * 24;
      ctx.font = '17px Consolas, monospace';
      ctx.fillStyle = i % 7 === 1 ? '#527f86' : i % 4 === 2 ? '#687a9f' : '#59668b';
      ctx.fillText(words[i % words.length], 66 + (i % 4) * 15, y);
      ctx.fillStyle = i % 4 === 0 ? '#518a85' : '#3f5076';
      ctx.fillText(i % 4 === 0 ? '●' : '··', 606, y);
      ctx.fillRect(630, y - 7, 48 + (i * 113) % 258, 2);
    }
    ctx.fillStyle = '#3d5574';
    ctx.fillText('ctrl + alt + t', 65, 913);
  });
}

function glowDisc() {
  return paintTexture(128, 128, (ctx) => {
    const glow = ctx.createRadialGradient(64, 64, 0, 64, 64, 62);
    glow.addColorStop(0, '#ffffffff');
    glow.addColorStop(0.36, '#ffffff9b');
    glow.addColorStop(1, '#ffffff00');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, 128, 128);
  });
}

function floorDisc(scene: T.Scene, map: T.Texture, color: string, x: number, z: number, size: number, opacity: number) {
  const plane = new T.Mesh(new T.PlaneGeometry(size, size),
    new T.MeshBasicMaterial({map, color, transparent: true, opacity, depthWrite: false, toneMapped: false}));
  plane.rotation.x = -Math.PI / 2;
  plane.position.set(x, 0.027, z);
  scene.add(plane);
  return plane;
}

function landscape(scene: T.Scene, windows: T.Texture) {
  box(scene, solid('#0c1021'), [12, 7, 0.08], [0, 2.82, -2.56]);
  const screen = new T.Mesh(new T.PlaneGeometry(5.34, 5.11), new T.MeshBasicMaterial({
    map: terminal(), color: '#b5b8f0', toneMapped: false,
  }));
  screen.position.set(0.15, 2.43, -2.49);
  scene.add(screen);
  box(scene, solid('#111625', 0.56, 0.34), [7.3, 0.086, 7.4], [0, -0.054, 0.52]);
  const tile = new T.InstancedMesh(boxGeometry, solid('#ffffff', 0.59, 0.28), 11 * 12);
  const matrix = new T.Matrix4();
  const color = new T.Color();
  for (let row = 0; row < 12; row++) {
    for (let col = 0; col < 11; col++) {
      matrix.makeScale(0.558, 0.027, 0.624);
      matrix.setPosition((col - 5) * 0.575, -0.006, (row - 4) * 0.643);
      tile.setMatrixAt(row * 11 + col, matrix);
      color.set(['#16243a', '#192739', '#111d33', '#152032', '#151c30'][(col * 7 + row * 11) % 5]);
      tile.setColorAt(row * 11 + col, color);
    }
  }
  scene.add(tile);
  const lightBlue = diode('#7594ed', 1.25);
  const lightMint = diode('#77cba8', 0.81);
  for (let i = -3; i <= 4; i++) {
    box(scene, lightBlue, [0.208, 0.016, 0.034], [-1.57, 0.022, 0.622 * i]);
    box(scene, i % 3 === 0 ? lightMint : lightBlue, [0.195, 0.016, 0.034], [1.58, 0.022, 0.622 * i + 0.24]);
  }
  box(scene, solid('#1c2a42', 0.6, 0.26), [7.5, 0.32, 0.31], [0, 0.12, -2.04]);
  box(scene, lightBlue, [3.43, 0.023, 0.016], [0.48, 0.216, -1.88]);
  const lightPads = glowDisc();
  floorDisc(scene, lightPads, '#5671dc', -1.47, 0.61, 2.85, 0.47);
  floorDisc(scene, lightPads, '#4bbaa2', 1.56, 0.12, 2.60, 0.47);
  floorDisc(scene, lightPads, '#07101a', -0.76, 0.07, 1.04, 0.78);
  floorDisc(scene, lightPads, '#07101a', 0.80, 0.03, 0.94, 0.74);
  const torchPool = floorDisc(scene, lightPads, '#addde0', 0.27, 0.94, 1.61, 0);
  torchPool.position.y = 0.032;

  const rig = pivot(scene, 0.13, 0.0, 0.99);
  rig.rotation.y = -0.36;
  box(rig, solid('#141e24', 0.35, 0.52), [0.25, 0.055, 0.132], [0, 0.034, 0], true);
  box(rig, solid('#656b78', 0.31, 0.68), [0.077, 0.046, 0.108], [0.159, 0.032, 0], true);
  box(rig, solid('#a9b9c0'), [0.044, 0.012, 0.012], [0.165, 0.062, 0.035]);
  box(rig, solid('#4c857e'), [0.09, 0.01, 0.056], [0.019, 0.065, 0]);
  box(rig, diode('#8dea98', 0.46), [0.028, 0.012, 0.027], [-0.080, 0.066, 0.025]);

  const desktop = pivot(scene, -0.38, 0.88, 0.42);
  const pc = solid('#283b49', 0.47, 0.34);
  box(desktop, pc, [0.982, 0.71, 0.045], [0, 0.359, 0], true);
  box(desktop, pc, [1.08, 0.048, 0.529], [0, 0.0, 0.205], true);
  box(desktop, solid('#172730'), [0.597, 0.012, 0.242], [0, 0.025, 0.172], true);
  box(desktop, diode('#6598a7', 0.21), [1.02, 0.014, 0.035], [0, -0.029, 0.463]);
  box(desktop, solid('#293849', 0.42, 0.36), [0.091, 0.69, 0.106], [0, -0.368, 0.15]);
  box(desktop, solid('#202d3e', 0.54, 0.29), [0.55, 0.049, 0.411], [0, -0.725, 0.15], true);
  const desktopDisplay = new T.Mesh(new T.PlaneGeometry(0.905, 0.633),
    new T.MeshBasicMaterial({map: windows, toneMapped: false}));
  desktopDisplay.position.set(0, 0.363, 0.026);
  desktop.add(desktopDisplay);
  return {torchPool, usb: rig, desktop};
}

function texture(url: string) {
  return new T.TextureLoader().loadAsync(url).then(tex => {
    tex.colorSpace = T.SRGBColorSpace;
    tex.anisotropy = 4;
    return tex;
  });
}

export type Stage = {
  draw: (time: number, beat: Beat, end: number) => void;
  dispose: () => void;
};

export async function buildStage(canvas: HTMLCanvasElement, assets: {mark: string; android: string; windows: string}) {
  const renderer = new T.WebGLRenderer({
    canvas, antialias: true, alpha: false, powerPreference: 'high-performance', preserveDrawingBuffer: true,
  });
  const renderWidth = Math.min(WIDTH, Math.max(540, window.innerWidth));
  renderer.setSize(renderWidth, Math.round(renderWidth * HEIGHT / WIDTH), false);
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  const scene = new T.Scene();
  scene.background = new T.Color('#111529');
  scene.fog = new T.FogExp2('#151d35', 0.053);
  const camera = new T.PerspectiveCamera(36, WIDTH / HEIGHT, 0.1, 26);
  const [mark, android, windows] = await Promise.all([texture(assets.mark), texture(assets.android), texture(assets.windows)]);
  const {torchPool, desktop} = landscape(scene, windows);
  const human = person(scene);
  const robot = assistant(scene, mark);
  const handset = phone(human.grip, android);
  const torchPhone = phone(scene, android);
  torchPhone.position.set(-0.23, 0.26, 0.56);
  torchPhone.rotation.set(-0.33, 0.25, -0.15);
  const ambient = new T.HemisphereLight('#b6c5ed', '#242245', 1.89);
  scene.add(ambient);
  const key = new T.DirectionalLight('#ffd0ac', 2.5);
  key.position.set(-3.7, 5.1, 4.8);
  scene.add(key);
  const fill = new T.DirectionalLight('#8aa2ff', 2.42);
  fill.position.set(2.3, 3.3, -2.3);
  scene.add(fill);
  const side = new T.DirectionalLight('#70e0bb', 1.56);
  side.position.set(4.4, 3.0, 2.7);
  scene.add(side);
  const torch = new T.PointLight('#cbffef', 0, 4.3, 1.25);
  torch.position.set(-0.28, 0.39, 0.64);
  scene.add(torch);

  const draw = (time: number, beat: Beat, end: number) => {
    const t = time - beat.start;
    const length = end - beat.start;
    const talking = t > (beat.reaction === 'punch' ? 0.47 : 0.11) && t < length - 0.23;
    const talk = (count: number) => Math.floor(t * count) % 3;
    const light = beat.view === 'light' ? pace(t / 0.29) : 0;
    const result = beat.view === 'result';
    human.root.visible = !result;
    robot.root.visible = beat.view !== 'light';
    handset.visible = beat.reaction === 'ask' && !result;
    torchPhone.visible = beat.view === 'light';
    desktop.visible = result;
    desktop.rotation.set(-0.04, 0.1 + 0.035 * Math.sin(t * 2), -0.07);
    desktop.position.y = 0.88 + 0.075 * pace(t / 0.6);
    torch.intensity = 9.1 * light;
    torchPool.material.opacity = 0.70 * light;
    key.intensity = 2.48 - 2.06 * light;
    side.intensity = 1.45 - 0.71 * light;

    const humanSpeaks = beat.speaker === 'human' && talking;
    const robotSpeaks = beat.speaker === 'troika' && talking;
    const glance = humanSpeaks ? 0.10 : 0.18;
    const gesture = (beat.reaction === 'ask' ? 0.70 : beat.reaction === 'question' ? 0.38 : 0.18) * pace(t / 0.39)
      * (1 - 0.34 * pace((t - length + 0.43) / 0.41));
    const doubt = beat.reaction === 'smirk' || beat.reaction === 'question';
    human.root.rotation.y = glance + 0.048 * Math.sin(t * 1.65);
    human.body.rotation.z = (humanSpeaks ? 0.03 : -0.014) + 0.018 * Math.sin(time * 2);
    human.head.rotation.set(-0.015 - 0.077 * gesture + 0.025 * Math.sin(t * 5), 0.009 + 0.07 * gesture,
      doubt ? -0.095 * pace(t / 0.68) : -0.017 + 0.032 * Math.sin(t * 2.4));
    human.limbs.forEach(({shoulder, elbow}, index) => {
      const sign = index === 0 ? -1 : 1;
      shoulder.rotation.z = sign * (0.065 + 0.17 * gesture + 0.013 * Math.sin(t * 3.4));
      shoulder.rotation.x = -0.05 - (index === 1 ? 0.49 : 0.22) * gesture;
      elbow.rotation.x = index === 1 ? -1.75 * gesture : -0.28 * gesture;
    });
    const humanBlink = Math.max(blink(t, length * 0.44), blink(t, length - 0.4));
    human.eyes.forEach(({lid, iris}) => {
      lid.scale.y = 1 - 0.93 * humanBlink;
      iris.position.x = 0.026 * (0.25 + 0.62 * pace(t / 0.75));
    });
    human.eyebrows.forEach((brow, index) => {
      brow.position.y = 0.431 + (doubt ? (index === 0 ? 0.046 : 0.009) : 0.012 * gesture);
      brow.rotation.z = (index === 0 ? 1 : -1) * (doubt ? 0.18 : 0.08);
    });
    human.mouth(humanSpeaks ? talk(6.6) : beat.reaction === 'smirk' ? 3 : 0);

    const bob = robotSpeaks ? 0.014 * Math.sin(t * 13.1) : 0.011 * Math.sin(time * 3.6);
    robot.root.rotation.y = -0.18 + 0.04 * Math.sin(t * 3.1);
    robot.core.position.y = 0.52 + bob + (beat.reaction === 'quick' ? 0.046 * pace(t / 0.32) : 0);
    robot.core.rotation.set(
      beat.reaction === 'punch' ? -0.075 * pace(t / 0.68) : 0.029 * Math.sin(t * 3.7),
      0.04 * Math.sin(t * 4.4),
      beat.reaction === 'punch' ? -0.095 * pace(t / 0.63) : 0.036 * Math.sin(t * 3.61),
    );
    robot.antenna.rotation.z = 0.08 * Math.sin(t * 6.9);
    robot.tip.scale.setScalar(0.083 + 0.011 * Math.sin(t * 11));
    robot.arms.forEach((arm, i) => {
      arm.rotation.z = (i === 0 ? -1 : 1) * (0.045 + (robotSpeaks ? 0.11 : 0) + 0.05 * Math.sin(t * 4.2));
      arm.rotation.x = robotSpeaks ? -0.20 - 0.07 * Math.sin(t * 6.6) : -0.05;
    });
    const rb = Math.max(blink(t, beat.reaction === 'punch' ? 0.36 : length * 0.58),
      blink(t, length - 0.43));
    robot.eyes.forEach(({lid, iris}, index) => {
      const wink = beat.reaction === 'punch' && index === 1 ? blink(t, 2.28, 0.165) : 0;
      lid.scale.y = 1 - 0.89 * Math.max(rb, wink);
      iris.position.x = -0.019 - 0.011 * Math.sin(t * 3.6);
    });
    robot.brows.forEach((brow, index) => {
      brow.rotation.z = (index === 0 ? 1 : -1) * (0.13 + 0.13 * Math.sin(t * 4));
      brow.position.y = 0.541 + (beat.reaction === 'punch' && index === 0 ? 0.037 * pace(t / 0.62) : 0);
    });
    robot.mouth(beat.reaction === 'punch' && t > 1.68 ? 1 : robotSpeaks ? talk(7.5) : 1);

    const move = pace(t / Math.max(0.1, length));
    const sway = 0.018 * Math.sin(t * 3.1);
    let look: T.Vector3;
    switch (beat.view) {
      case 'person':
        camera.position.copy(V(-1.05 + move * 0.21 + sway, 1.80 + move * 0.12,
          2.64 - move * 0.15 + (beat.reaction === 'ask' ? 0.48 : 0)));
        camera.fov = 36;
        look = V(-0.76 + 0.034 * move, beat.reaction === 'ask' ? 1.95 : 2.12, 0.01);
        break;
      case 'assistant':
        camera.position.copy(V(1.29 - move * 0.27, 1.22 + sway, 3.25 - move * 0.30));
        camera.fov = 33;
        look = V(0.8, 1.183 + 0.02 * move, 0.04);
        break;
      case 'light':
        camera.position.copy(V(0.82 - move * 0.31, 0.82 - move * 0.12, 2.77 - 0.34 * move));
        camera.fov = 35;
        look = V(0.062, 0.25, 0.52);
        break;
      case 'result':
        camera.position.copy(V(0.47 - 0.17 * move, 1.42 + 0.07 * move, 5.34 - 0.21 * move));
        camera.fov = 39;
        look = V(0.26, 1.47, 0.01);
        break;
      case 'wide':
        camera.position.copy(V(0.19 + 0.08 * move, 1.83 + move * 0.17, 6.64 + move * 0.73));
        camera.fov = 40;
        look = V(0.05, 1.61, 0);
        break;
    }
    camera.updateProjectionMatrix();
    camera.lookAt(look);
    camera.rotateZ(0.004 * Math.sin(t * 3.52));
    renderer.render(scene, camera);
  };
  return {draw, dispose: () => renderer.dispose()} satisfies Stage;
}
