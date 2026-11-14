import {interpolate, useCurrentFrame} from 'remotion';
import {DashboardCard} from '../components/DashboardCard';
import {Heading, Reveal} from '../components/Shared';

const services = [
  {index:'01', title:'Centralisez', description:'Votre patrimoine et vos relevés', details:['Import Excel & CSV','Connexion API fournisseur'], symbol:'↥'},
  {index:'02', title:'Surveillez', description:'Vos consommations, fluide par fluide', details:['Électricité · eau · gaz','Chaleur · PAC · solaire'], symbol:'⌁'},
  {index:'03', title:'Intervenez', description:'Du constat au suivi des travaux', details:['Alertes classées par priorité','Bons de travaux & prestataires'], symbol:'↗'},
];

export function ServicesScene() {
  const image=useCurrentFrame();
  return <>
    <Heading step="VOS DONNÉES. UN PARCOURS COMPLET." title="Connectez. Analysez. Agissez." sub="Les services essentiels à la gestion énergétique de votre parc."/>
    <div className="services-grid">
      {services.map((service,index)=><DashboardCard key={service.index} delay={15+index*22}>
        <div className="service-top"><span className="service-symbol">{service.symbol}</span><span className="eyebrow">{service.index}</span></div>
        <h2>{service.title}</h2><p>{service.description}</p>
        <div className="service-details">{service.details.map(detail=><div key={detail}><span className="blue">✓</span> {detail}</div>)}</div>
        <div className="service-track"><div style={{width:`${interpolate(image,[30+index*22,120+index*22],[0,100],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}%`}}/></div>
      </DashboardCard>)}
    </div>
    <Reveal delay={110}><p className="services-caption">Une lecture métier de vos données. Des priorités pour vos équipes.</p></Reveal>
  </>;
}
