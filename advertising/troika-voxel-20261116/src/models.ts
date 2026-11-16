import * as T from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';

export const boxGeometry = new T.BoxGeometry(1, 1, 1);
const bevelGeometry = new RoundedBoxGeometry(1, 1, 1, 1, 0.037);
const softGeometry = new RoundedBoxGeometry(1, 1, 1, 2, 0.073);

export function solid(color: string, roughness = 0.68, metalness = 0) {
  return new T.MeshStandardMaterial({color, roughness, metalness});
}

export function diode(color: string, strength = 0.75) {
  return new T.MeshStandardMaterial({color, emissive: color, emissiveIntensity: strength, roughness: 0.42});
}

export function box(parent: T.Object3D, material: T.Material, size: number[], position: number[], bevel: boolean | 'soft' = false) {
  const mesh = new T.Mesh(bevel === 'soft' ? softGeometry : bevel ? bevelGeometry : boxGeometry, material);
  mesh.scale.set(size[0], size[1], size[2]);
  mesh.position.set(position[0], position[1], position[2]);
  parent.add(mesh);
  return mesh;
}

export function pivot(parent: T.Object3D, x: number, y: number, z = 0) {
  const obj = new T.Group();
  obj.position.set(x, y, z);
  parent.add(obj);
  return obj;
}

function eye(parent: T.Object3D, x: number, y: number, z: number,
  paper: T.Material, pupil: T.Material, size: number, catchlight: T.Material) {
  const lid = pivot(parent, x, y, z);
  box(lid, paper, [size, size * 0.84, 0.016], [0, 0, 0]);
  const iris = pivot(lid, 0, -0.002, 0.012);
  box(iris, pupil, [size * 0.47, size * 0.73, 0.015], [0, 0, 0]);
  box(iris, catchlight, [size * 0.17, size * 0.15, 0.011], [-size * 0.075, size * 0.14, 0.011]);
  return {lid, iris};
}

function avatarMouth(parent: T.Object3D, y: number, z: number, mat: T.Material, pixel: number) {
  const posed: T.Group[] = [];
  const maps = [
    [[-1, 0], [0, 0], [1, 0]],
    [[-2, 0], [-1, -1], [0, -1], [1, -1], [2, 0]],
    [[-1, 0], [0, 0], [1, 0], [-1, -1], [0, -1], [1, -1]],
    [[-1, -1], [0, -1], [1, 0], [2, 1]],
  ];
  for (const marks of maps) {
    const group = pivot(parent, 0, y, z);
    for (const [x, row] of marks) {
      box(group, mat, [pixel * 1.02, pixel * 0.94, 0.012], [x * pixel, row * pixel, 0]);
    }
    posed.push(group);
  }
  return (pose: number) => posed.forEach((group, i) => { group.visible = i === pose; });
}

export function person(scene: T.Scene) {
  const root = pivot(scene, -0.76, 0);
  const body = pivot(root, 0, 0);
  const trousers = solid('#263443');
  const seam = solid('#344653');
  const shoes = solid('#e3d8bb');
  const sole = solid('#646061');
  const knit = solid('#528675');
  const seamKnit = solid('#3f6a5d');
  const thread = solid('#aaccaa');
  const face = solid('#d59367');
  const nose = solid('#ebb482');
  const peach = solid('#bc745d');
  const hair = solid('#2e202b');
  const cap = solid('#ce884b');
  const capStripe = solid('#e3a65e');
  const paper = solid('#f0dcc5');
  const pupils = solid('#3c383e');
  const white = solid('#fff5df');

  for (const sign of [-1, 1]) {
    const x = sign * 0.197;
    box(body, trousers, [0.332, 0.69, 0.355], [x, 0.51, 0], true);
    box(body, seam, [0.036, 0.66, 0.018], [x + sign * 0.078, 0.51, 0.180]);
    box(body, sole, [0.35, 0.066, 0.526], [x, 0.040, 0.07], true);
    box(body, shoes, [0.34, 0.15, 0.515], [x, 0.14, 0.07], true);
    box(body, white, [0.26, 0.014, 0.047], [x, 0.218, 0.15]);
    box(body, white, [0.26, 0.014, 0.042], [x, 0.218, 0.207]);
  }
  box(body, trousers, [0.72, 0.13, 0.38], [0, 0.85, 0], true);
  box(body, knit, [0.72, 0.68, 0.39], [0, 1.205, 0.005], true);
  box(body, seamKnit, [0.73, 0.095, 0.404], [0, 0.93, 0.012]);
  box(body, seamKnit, [0.75, 0.16, 0.41], [0, 1.50, -0.005], true);
  box(body, knit, [0.41, 0.14, 0.4], [0, 1.60, -0.04], true);
  box(body, seamKnit, [0.33, 0.12, 0.024], [0, 1.08, 0.21], true);
  for (const side of [-1, 1]) box(body, thread, [0.018, 0.18, 0.018], [side * 0.075, 1.43, 0.219]);
  const limbs = [-1, 1].map((sign) => {
    const shoulder = pivot(body, sign * 0.43, 1.50);
    box(shoulder, knit, [0.225, 0.31, 0.34], [0, -0.125, -0.005], true);
    const elbow = pivot(shoulder, 0, -0.277, 0);
    box(elbow, knit, [0.213, 0.26, 0.316], [0, -0.11, 0.005], true);
    box(elbow, seamKnit, [0.212, 0.08, 0.313], [0, -0.23, 0.006]);
    box(elbow, face, [0.198, 0.19, 0.264], [0, -0.341, 0.018], true);
    box(elbow, peach, [0.075, 0.092, 0.116], [-sign * 0.087, -0.305, 0.104], true);
    return {shoulder, elbow};
  });

  const head = pivot(body, 0, 1.663, 0.004);
  box(head, face, [0.65, 0.62, 0.525], [0, 0.313, 0], true);
  box(head, face, [0.49, 0.11, 0.45], [0, 0.044, 0.049], true);
  box(head, hair, [0.67, 0.34, 0.455], [0, 0.45, -0.06], true);
  box(head, face, [0.609, 0.46, 0.10], [0, 0.268, 0.239], true);
  box(head, nose, [0.114, 0.105, 0.105], [0, 0.234, 0.318], true);
  box(head, peach, [0.112, 0.026, 0.01], [0, 0.187, 0.369]);
  for (const sign of [-1, 1]) {
    box(head, face, [0.105, 0.173, 0.22], [sign * 0.343, 0.29, 0.012], true);
    box(head, peach, [0.026, 0.102, 0.132], [sign * 0.398, 0.285, 0.016]);
    box(head, hair, [0.074, 0.18, 0.10], [sign * 0.290, 0.437, 0.241]);
    box(head, peach, [0.063, 0.018, 0.012], [sign * 0.18, 0.223, 0.294]);
  }
  box(head, hair, [0.54, 0.087, 0.158], [0, 0.494, 0.214]);
  box(head, hair, [0.105, 0.083, 0.147], [-0.263, 0.447, 0.224]);
  box(head, cap, [0.702, 0.122, 0.568], [0, 0.562, -0.006], true);
  box(head, cap, [0.617, 0.146, 0.515], [0, 0.681, -0.026], true);
  box(head, capStripe, [0.53, 0.072, 0.444], [0, 0.77, -0.045], true);
  box(head, capStripe, [0.664, 0.040, 0.014], [0, 0.571, 0.283]);
  for (let index = 0; index < 7; index++) {
    box(head, capStripe, [0.026, 0.066, 0.01], [0.075 * (index - 3), 0.682, 0.237]);
  }
  const eyes = [-0.144, 0.144].map(x => eye(head, x, 0.33, 0.298, paper, pupils, 0.126, white));
  const eyebrows = [-0.144, 0.144].map(x => box(head, hair, [0.137, 0.037, 0.032], [x, 0.431, 0.306], true));
  const mouth = avatarMouth(head, 0.122, 0.308, solid('#784a44'), 0.039);
  const grip = pivot(limbs[1].elbow, 0.028, -0.32, 0.155);
  return {root, body, head, limbs, eyes, eyebrows, mouth, grip};
}

export function assistant(scene: T.Scene, mark: T.Texture) {
  const root = pivot(scene, 0.80, 0);
  const core = pivot(root, 0, 0.52);
  const shell = solid('#53a389', 0.43, 0.27);
  const front = solid('#152d29', 0.37, 0.20);
  const edge = solid('#34685d', 0.49, 0.31);
  const warm = solid('#d99b58', 0.43, 0.34);
  const glow = diode('#a1f8c3', 0.63);
  const low = diode('#4eaf83', 0.27);
  const blush = diode('#ed987d', 0.08);
  const near = solid('#1c2d35', 0.57, 0.3);
  const legs = [-0.298, 0.298].map(x => {
    const leg = pivot(root, x, 0.47);
    box(leg, shell, [0.18, 0.318, 0.20], [0, -0.176, -0.07], true);
    box(leg, near, [0.235, 0.11, 0.298], [0, -0.406, -0.005], true);
    box(leg, low, [0.112, 0.021, 0.016], [0, -0.388, 0.154]);
    return leg;
  });
  box(core, edge, [1.00, 0.745, 0.738], [0, 0.335, -0.021], 'soft');
  box(core, shell, [1.05, 0.75, 0.68], [0, 0.386, 0.032], 'soft');
  box(core, shell, [0.96, 0.077, 0.65], [0, 0.729, 0.036], 'soft');
  box(core, front, [0.927, 0.57, 0.046], [0, 0.364, 0.374], 'soft');
  box(core, solid('#20463b', 0.31, 0.19), [0.858, 0.501, 0.024], [0, 0.36, 0.404], 'soft');
  box(core, low, [0.26, 0.018, 0.012], [0, 0.128, 0.421], true);
  box(core, warm, [0.019, 0.108, 0.019], [0.47, 0.499, 0.41]);
  box(core, warm, [0.019, 0.065, 0.019], [0.47, 0.389, 0.41]);
  for (const side of [-1, 1]) {
    for (let i = 0; i < 4; i++) box(core, front,
      [0.018, 0.045, 0.124], [side * 0.527, 0.503 - i * 0.068, -0.110]);
  }
  const antenna = pivot(core, 0.35, 0.758, -0.115);
  box(antenna, edge, [0.109, 0.062, 0.1], [0, 0.028, 0], true);
  box(antenna, warm, [0.037, 0.222, 0.037], [0, 0.122, 0], true);
  const tip = box(antenna, glow, [0.092, 0.081, 0.088], [0, 0.24, 0], true);
  const badge = new T.Mesh(new T.PlaneGeometry(0.146, 0.146), new T.MeshBasicMaterial({
    map: mark, transparent: true, depthWrite: false, toneMapped: false,
  }));
  badge.position.set(-0.320, 0.586, 0.425);
  core.add(badge);
  const eyes = [-0.167, 0.167].map(x => {
    const lid = pivot(core, x, 0.421, 0.423);
    box(lid, glow, [0.141, 0.156, 0.017], [0, 0, 0], 'soft');
    const iris = pivot(lid, 0, 0, 0.018);
    box(iris, front, [0.054, 0.079, 0.008], [0, -0.004, 0], true);
    box(iris, diode('#f5ffe8', 0.39), [0.024, 0.022, 0.007], [-0.009, 0.016, 0.006]);
    box(core, blush, [0.064, 0.028, 0.014], [x * 1.64, 0.304, 0.429], true);
    return {lid, iris};
  });
  const brows = [-0.167, 0.167].map(x => box(core, low, [0.082, 0.018, 0.010], [x, 0.541, 0.429], true));
  const mouth = avatarMouth(core, 0.287, 0.433, glow, 0.035);
  const arms = [-1, 1].map(sign => {
    const arm = pivot(core, sign * 0.51, 0.484, -0.005);
    box(arm, near, [0.13, 0.13, 0.197], [sign * 0.055, 0, 0], true);
    box(arm, edge, [0.126, 0.239, 0.155], [sign * 0.090, -0.121, 0], true);
    box(arm, shell, [0.169, 0.109, 0.172], [sign * 0.09, -0.246, 0.008], true);
    return arm;
  });
  return {root, legs, core, antenna, tip, eyes, mouth, arms, brows};
}

export function phone(parent: T.Object3D, texture: T.Texture) {
  const handset = pivot(parent, 0.012, -0.075);
  handset.rotation.set(0.02, 0.03, -0.12);
  box(handset, solid('#607373', 0.37, 0.5), [0.232, 0.476, 0.043], [0, 0, 0], true);
  box(handset, solid('#131c20'), [0.216, 0.442, 0.028], [0, 0, 0.013], true);
  const display = new T.Mesh(new T.PlaneGeometry(0.199, 0.425),
    new T.MeshBasicMaterial({map: texture, toneMapped: false}));
  display.position.set(0, 0, 0.029);
  handset.add(display);
  box(handset, diode('#cbffe0', 1.0), [0.067, 0.021, 0.007], [-0.063, 0.192, -0.024]);
  return handset;
}
