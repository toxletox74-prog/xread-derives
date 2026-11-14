import {spring,useCurrentFrame,useVideoConfig} from 'remotion';
import type {ReactNode} from 'react';
export function DashboardCard({children,delay=0,style={}}:{children:ReactNode;delay?:number;style?:React.CSSProperties}) {
 const f=useCurrentFrame(),{fps}=useVideoConfig(); const p=spring({frame:f-delay,fps,config:{damping:24,stiffness:90}});
 return <div className="card" style={{opacity:p,transform:`translateY(${(1-p)*28}px)`,...style}}>{children}</div>;
}
