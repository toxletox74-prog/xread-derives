import {interpolate,useCurrentFrame} from 'remotion';
import {actual,reference} from '../data/demoData';
export function AnimatedConsumptionChart({compact=false}:{compact?:boolean}) {
 const f=useCurrentFrame(); const p=interpolate(f,[15,135],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 const path=(vs:number[])=>vs.map((v,i)=>`${i?'L':'M'}${80+i*31.7},${370-(v-700)*.4}`).join(' ');
 return <svg viewBox="0 0 1080 460" style={{width:'100%',display:'block'}} role="img" aria-label="Référence de 30 000 kWh et consommation de 36 000 kWh : écart de 6 000 kWh">
 <defs><linearGradient id="drift" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#FBBF24" stopOpacity=".30"/><stop offset="1" stopColor="#FBBF24" stopOpacity=".02"/></linearGradient><clipPath id="reveal"><rect width={1080*p} height="460"/></clipPath></defs>
 {[800,1000,1200,1400].map(v=><g key={v}><line x1="80" x2="1000" y1={370-(v-700)*.4} y2={370-(v-700)*.4} stroke="#23324A"/><text x="60" y={376-(v-700)*.4} fill="#9AA9BE" fontSize="18" textAnchor="end">{v}</text></g>)}
 <g clipPath="url(#reveal)"><path d={`${path(actual)} L999.3,250 L80,250 Z`} fill="url(#drift)"/><path d={path(reference)} fill="none" stroke="#8AB4FF" strokeWidth="4" strokeDasharray="10 9"/><path d={path(actual)} fill="none" stroke="#FBBF24" strokeWidth="5" strokeLinejoin="round"/>
 <circle cx="999.3" cy="90" r="7" fill="#FBBF24"/></g>
 {[['01',80],['08',302],['16',555],['23',777],['30',1000]].map(([d,x])=><text key={d} x={x} y="405" fill="#9AA9BE" fontSize="20" textAnchor="middle">{d} nov.</text>)}
 <text x="80" y="32" fill="#9AA9BE" fontSize="19">kWh / jour</text>
 {!compact&&<g opacity={interpolate(f,[130,160],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}><rect x="640" y="8" width="360" height="55" rx="12" fill="#30281C" stroke="#8A6924"/><text x="660" y="43" fill="#FBBF24" fontSize="23">+40 % depuis le 16 novembre</text></g>}
 </svg>;
}
