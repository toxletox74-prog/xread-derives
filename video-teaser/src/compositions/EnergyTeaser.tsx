import {AbsoluteFill,Audio,Sequence,staticFile,useCurrentFrame,useVideoConfig,interpolate} from 'remotion';
import {scenes,TOTAL} from '../config/timeline';
import {branding} from '../config/branding';
import {ProblemScene} from '../scenes/ProblemScene';
import {DashboardScene} from '../scenes/DashboardScene';
import {AnalysisScene} from '../scenes/AnalysisScene';
import {ValueScene} from '../scenes/ValueScene';
import {OutroScene} from '../scenes/OutroScene';
import {Brand} from '../components/Shared';
const components=[ProblemScene,DashboardScene,AnalysisScene,ValueScene,OutroScene];
function Scene({children,duration}:{children:React.ReactNode;duration:number}){const f=useCurrentFrame();return <AbsoluteFill style={{opacity:interpolate(f,[0,14,duration-14,duration-1],[0,1,1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}}>{children}</AbsoluteFill>}
export function EnergyTeaser(){const f=useCurrentFrame();const {width,height}=useVideoConfig();const vertical=height>width;const designWidth=vertical?1080:1920;const scale=width/designWidth;return <AbsoluteFill style={{background:branding.navy}}><div className={vertical?'stage vertical':'stage'} style={{width:designWidth,height:height/scale,transform:`scale(${scale})`,transformOrigin:'top left'}}><div className="ambient" style={{transform:`translateX(${Math.sin(f/250)*35}px)`}}/><div className="top-brand"><Brand/><span>ENERGY INTELLIGENCE</span></div>{scenes.map((s,i)=>{const C=components[i];return <Sequence key={s.id} from={s.from} durationInFrames={s.duration}><Scene duration={s.duration}><main className="content"><C/></main></Scene></Sequence>})}<footer><span>DONNÉES FICTIVES · DÉMONSTRATION PRODUIT</span><span>{String(Math.min(60,Math.floor(f/30))).padStart(2,'0')} / 60</span></footer><div className="progress" style={{width:`${f/(TOTAL-1)*100}%`}}/></div>{branding.music&&<Audio src={staticFile('audio/score.wav')} volume={frame=>interpolate(frame,[0,45,1740,1799],[0,.55,.55,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}/>} {branding.voiceover&&<Audio src={staticFile(branding.voiceover)} volume={1}/>}</AbsoluteFill>}
