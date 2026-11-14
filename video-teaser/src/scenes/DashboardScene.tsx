import {Img,staticFile,useVideoConfig} from 'remotion';
import {CameraZoom} from '../components/CameraZoom';
import {DashboardCard} from '../components/DashboardCard';
import {Heading} from '../components/Shared';
import {AnimatedCounter} from '../components/AnimatedCounter';
import {buildings} from '../data/demoData';
export function DashboardScene(){const {width,height}=useVideoConfig();const v=height>width;return <><Heading step="01 / DÉTECTER" title="Votre patrimoine. Une vision claire." sub="Détectez les dérives énergétiques de votre patrimoine."/><div className="dashboard-layout"><CameraZoom><div className="app-window"><div className="window-bar"><i/><i/><i/><span>Xread Dérives / Tableau de bord</span></div><Img className="dashboard-capture" src={staticFile(v?'assets/dashboard-vertical.png':'assets/dashboard.png')}/></div></CameraZoom><div className="building-stack">{buildings.map((b,i)=><DashboardCard key={b.name} delay={45+i*14}><div className="row"><span className="badge">{b.status}</span><span className="muted">0{i+1}</span></div><h3>{b.name}</h3><p>{b.type}</p><div className="metric-small"><AnimatedCounter value={b.cost} delay={65+i*14}/> <small>CHF / mois estimés</small></div></DashboardCard>)}</div></div></>}
