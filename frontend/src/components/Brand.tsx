import { Smile } from 'lucide-react';
export default function Brand({light=false}:{light?:boolean}){return <div className={'brand '+(light?'light':'')}><span className="brandmark"><Smile/></span><span><b>Aves</b><small>Dental Clinic</small></span></div>}
