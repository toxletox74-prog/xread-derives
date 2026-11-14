import {useCurrentFrame,interpolate} from 'remotion';
import {AnimatedConsumptionChart} from '../components/AnimatedConsumptionChart';
import {Reveal} from '../components/Shared';
export function ProblemScene(){const f=useCurrentFrame();return <div className="problem"><div className="eyebrow">L’ÉNERGIE MÉRITE VOTRE ATTENTION</div><h1>Vos bâtiments consomment<br/><span className="light">plus que prévu.</span></h1><div className="problem-chart" style={{opacity:interpolate(f,[20,45],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}}><AnimatedConsumptionChart compact/></div><Reveal delay={145}><h2 className="question">Mais savez-vous pourquoi ?</h2></Reveal></div>}
