import { CalendarDays, CircleAlert, FileText, LibraryBig, Settings2, Sparkles, Users } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import { Topbar } from '../components/DashboardParts';
import { Button } from '../components/UI';

const details:Record<string,{title:string;description:string;items:string[]}>= {
  'live-receptionist':{title:'Live AI Receptionist',description:'Monitor patient conversations, booking requests and AI handoffs in real time.',items:['12 active conversations','94% resolved by AI','2 handoffs waiting']},
  appointments:{title:'Appointments',description:'Review upcoming visits, appointment requests and schedule changes.',items:['28 appointments today','7 requests awaiting review','3 reschedule requests']},
  patients:{title:'Patients',description:'Search patient profiles, treatment status and recent clinic activity.',items:['1,482 patient records','24 active treatment plans','18 new this month']},
  doctors:{title:'Doctors',description:'Manage clinician schedules, availability and specialties.',items:['8 active doctors','74 appointments this week','96% schedule coverage']},
  'knowledge-base':{title:'Knowledge Base',description:'Maintain trusted answers used by the AI receptionist and clinic team.',items:['148 published articles','12 drafts','Updated 2 hours ago']},
  escalations:{title:'Escalations',description:'Review patient issues requiring human attention and clinical judgment.',items:['3 open escalations','1 high priority','Median response: 8 min']},
  analytics:{title:'Analytics',description:'Explore clinic performance, patient growth and receptionist outcomes.',items:['+18% appointments','+28% patient growth','91% AI resolution rate']},
  settings:{title:'Settings',description:'Configure clinic details, team access and notification preferences.',items:['Clinic profile complete','4 notification rules','Security checks passed']},
  schedule:{title:'My Schedule',description:'Navigate your clinical schedule and planned patient visits.',items:['8 appointments today','2 follow-ups','1 open slot']},
  conversations:{title:'Conversations',description:'Work through patient messages and AI assisted replies.',items:['8 waiting','5 AI handled','2 need follow-up']},
  'patient-requests':{title:'Patient Requests',description:'Review new patient, insurance and booking requests.',items:['7 appointment requests','3 insurance checks','2 new patient forms']},
  calendar:{title:'Clinic Calendar',description:'Coordinate staff availability, visits and clinic events.',items:['28 visits today','3 team events','2 available rooms']},
  handoffs:{title:'Handoffs',description:'Take over conversations transferred by the AI receptionist.',items:['4 assigned to you','2 high priority','Average wait: 4 min']},
  reports:{title:'Reports',description:'Review receptionist performance and patient service outcomes.',items:['96% response SLA','4.8 patient rating','187 conversations this week']},
};
const iconMap=[CalendarDays,Users,LibraryBig,CircleAlert,FileText,Settings2];
export default function RolePage({role}:{role:'admin'|'receptionist'|'doctor'}){const nav=useNavigate();const key=useLocation().pathname.split('/').filter(Boolean).pop()||'';const d=details[key]||details.appointments;return <div className="appShell"><Sidebar role={role}/><main className="dash"><Topbar role={role}/><div className="subpage"><div className="subpageTitle"><small>{role.toUpperCase()} WORKSPACE</small><h1>{d.title}</h1><p>{d.description}</p><Button onClick={()=>nav(`/${role}`)}>← Back to dashboard</Button></div><div className="subCards">{d.items.map((x,i)=>{const Icon=iconMap[i%iconMap.length];return <article key={x}><span><Icon/></span><strong>{x}</strong><p>Live mock data · backend integration pending</p><button onClick={()=>nav(`/${role}`)}>Open overview →</button></article>})}</div><section className="pendingPanel"><Sparkles/><div><h2>{d.title} workspace is ready for integration</h2><p>The navigation, layout, and interaction state are active. Connect this screen to the FastAPI endpoints when those contracts are available.</p></div></section></div></main></div>}
