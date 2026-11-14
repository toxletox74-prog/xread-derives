import {Brand,Reveal} from '../components/Shared';
import {branding} from '../config/branding';
export function OutroScene(){return <div className="outro"><Reveal><Brand/></Reveal><Reveal delay={25}><h1>Anticipez les dérives.<br/><span className="light">Maîtrisez vos consommations.</span></h1></Reveal><Reveal delay={70}><div className="cta">{branding.cta}<span>↗</span></div>{branding.url&&<div className="url">{branding.url}</div>}</Reveal><Reveal delay={100}><p className="outro-note">De la donnée énergétique à l’action.</p></Reveal></div>}
