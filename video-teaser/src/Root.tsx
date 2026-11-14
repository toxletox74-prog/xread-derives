import {Composition} from 'remotion';
import {EnergyTeaser} from './compositions/EnergyTeaser';
import {FPS,TOTAL} from './config/timeline';
import './style.css';
export function Root(){return <>{[['EnergyTeaser4K',3840,2160],['EnergyTeaser1080',1920,1080],['EnergyTeaserVertical',1080,1920]].map(([id,width,height])=><Composition key={id} id={String(id)} component={EnergyTeaser} width={Number(width)} height={Number(height)} fps={FPS} durationInFrames={TOTAL}/>)}</>}
