export const FPS = 30;
export const scenes = [
  {id: 'problem', from: 0, duration: 240},
  {id: 'services', from: 240, duration: 240},
  {id: 'dashboard', from: 480, duration: 300},
  {id: 'analysis', from: 780, duration: 360},
  {id: 'value', from: 1140, duration: 390},
  {id: 'outro', from: 1530, duration: 270},
] as const;
export const TOTAL = scenes.reduce((n, s) => n + s.duration, 0);
