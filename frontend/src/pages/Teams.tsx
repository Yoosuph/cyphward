import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import StrataField from '../components/StrataField';
import PublicHeader from '../components/PublicHeader';
import PublicFooter from '../components/PublicFooter';
import SocialFloat from '../components/SocialFloat';
import { usePageMotion } from '../lib/usePageMotion';

// Add `image: '/team/<name>.jpg'` once a real, approved headshot exists
// (about 1200x1500, consistent lighting). Until then the card shows initials.
const PEOPLE: { name: string; role: string; note: string; image?: string }[] = [
  {
    name: 'Yusuf Lawan Nuhu',
    role: 'Chief Executive Officer',
    note: 'Cybersecurity engineer and developer',
  },
  {
    name: 'Abdullahi Bala Musa',
    role: 'Chief Technology Officer',
    note: '',
  },
  {
    name: 'Abdullahi Kabir Sani',
    role: 'Marketing Strategist',
    note: '',
  },
];

function initials(name: string) {
  const parts = name.split(/\s+/).filter(Boolean);
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

export default function Teams() {
  const motionRef = usePageMotion<HTMLElement>();
  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />
      <PublicHeader />
      <main ref={motionRef} className="landing-container relative z-10 subpage">
        <header className="team-head rise-in">
          <div>
            <p className="eyebrow mb-3">TEAM</p>
            <h1 className="page-title">Meet our <em>team.</em></h1>
          </div>
          <p className="team-lede">
            Cyphward is built in Kano, Nigeria, by a small team. Questions about the
            product, a partnership or the press go to info@cyphward.com.
          </p>
        </header>

        <ul className="roster">
          {PEOPLE.map((person, index) => (
            <li key={person.name} className={`roster-card rise-in rise-in-${index + 2}`}>
              <figure className="roster-photo">
                {person.image ? (
                  <img src={person.image} alt="" loading="lazy" decoding="async" />
                ) : (
                  <span className="roster-initials" aria-hidden="true">{initials(person.name)}</span>
                )}
                <span className="roster-index">0{index + 1}</span>
              </figure>
              <div className="roster-copy">
                <h2>{person.name}</h2>
                <p className="role">{person.role}</p>
                {person.note && <p className="note">{person.note}</p>}
              </div>
            </li>
          ))}
        </ul>

        <section className="team-cta rise-in rise-in-4" data-reveal>
          <div>
            <p className="eyebrow mb-3">WORK WITH US</p>
            <h2 className="font-display text-2xl font-medium">Have a question for the team?</h2>
          </div>
          <Link to="/contact" className="btn btn-solid">
            WRITE TO US <ArrowRight size={14} />
          </Link>
        </section>
      </main>
      <PublicFooter anchorPrefix="/" />
      <SocialFloat />
    </div>
  );
}
