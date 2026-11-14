import {interpolate,useCurrentFrame} from 'remotion';
import type {ReactNode} from 'react';
export function CameraZoom({children,duration=360}:{children:ReactNode;duration?:number}) {
 const f=useCurrentFrame(); return <div style={{transform:`perspective(2200px) rotateX(${interpolate(f,[0,duration],[3,0])}deg) scale(${interpolate(f,[0,duration],[.96,1.035])})`,transformOrigin:'50% 45%'}}>{children}</div>;
}
