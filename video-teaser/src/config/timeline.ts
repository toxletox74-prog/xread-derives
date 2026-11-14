export const FPS = 30;
export const scenes = [
  {id: 'problem', from: 0, duration: 240},
  {id: 'dashboard', from: 240, duration: 360},
  {id: 'analysis', from: 600, duration: 450},
  {id: 'value', from: 1050, duration: 450},
  {id: 'outro', from: 1500, duration: 300},
] as const;
export const TOTAL = scenes.reduce((n, s) => n + s.duration, 0);
