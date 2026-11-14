import {interpolate, useCurrentFrame} from 'remotion';
export const number = (n:number) => Math.round(n).toLocaleString('fr-CH');
export function AnimatedCounter({value, delay=0}:{value:number;delay?:number}) {
 const f=useCurrentFrame(); return <>{number(interpolate(f,[delay,delay+45],[0,value],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}))}</>;
}
