import {Img,staticFile,interpolate,useCurrentFrame} from 'remotion';
import {branding} from '../config/branding';
import type {ReactNode} from 'react';
export function Brand(){return <div className="brand"><Img src={staticFile('assets/logo.svg')}/><span>{branding.name}</span></div>}
export function Reveal({children,delay=0}:{children:ReactNode;delay?:number}){const f=useCurrentFrame();const p=interpolate(f,[delay,delay+24],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});return <div style={{opacity:p,transform:`translateY(${(1-p)*20}px)`}}>{children}</div>}
export function Heading({step,title,sub}:{step:string;title:string;sub?:string}){return <Reveal><div className="eyebrow">{step}</div><h1>{title}</h1>{sub&&<p className="subtitle">{sub}</p>}</Reveal>}
