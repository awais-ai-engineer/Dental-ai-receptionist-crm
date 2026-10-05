import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_factory
from app.models import Clinic, KnowledgeDocument
from app.services.knowledge import ingest_text

DEMO_DOCUMENTS = (
    ("Opening hours and contact", "faq", """Aves Dental Clinic demo opening hours: Monday to Friday 9 AM–7 PM; Saturday 10 AM–4 PM; Sunday closed. Confirm holiday hours with clinic staff. If clinic contact details are missing from the knowledge base, say they are unavailable and ask staff to confirm them."""),
    ("Demo doctors and services", "manual", """Fictional demo doctors: Dr. Sara Khan — General Dentistry; Dr. Michael Reed — Orthodontics; Dr. Emily Carter — Endodontics; Dr. Daniel Brooks — Oral Surgery. The receptionist should confirm availability before offering an appointment. Pediatric or children's care is not confirmed in this demo; ask clinic staff before promising it."""),
    ("Fictional demo price guide", "faq", """These are fictional demo prices in USD, not binding quotes. General consultation: $40. Dental cleaning: $70–$100. Deep cleaning: $150–$250. Dental X-ray: $25. Tooth filling: $90–$180. Root canal: $450–$1,000 depending on tooth. Dental crown: $500–$1,000 depending on material. Simple extraction: $120–$220. Surgical extraction: $250–$450. Wisdom tooth removal: $200–$600. Teeth whitening: $300–$450. Traditional braces: $3,000–$4,500. Ceramic braces: $3,500–$5,000. Clear aligners: $3,500–$5,500. Dental implant with crown: $2,800–$4,000. Do not invent prices. Prices are estimates unless explicitly fixed; final treatment pricing may require a dentist examination."""),
    ("Demo appointment and safety policies", "manual", """Appointments require staff confirmation; a request is not a confirmed booking. Ask staff to confirm cancellation or rescheduling terms before promising a deadline or fee. Payment methods and insurance participation are not specified in this demo; ask clinic staff to verify them. The AI receptionist must not diagnose medical conditions or give treatment advice. If a person describes emergency symptoms or severe distress, stop routine booking and escalate to human clinic staff; advise contacting appropriate emergency services where needed. If clinic information is missing, acknowledge the gap instead of inventing an answer."""),
)


async def seed_aves_knowledge(db: AsyncSession, clinic_id: UUID) -> int:
    created = 0
    for title, source_type, content in DEMO_DOCUMENTS:
        exists = await db.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.clinic_id == clinic_id, KnowledgeDocument.title == title))
        if exists is None:
            await ingest_text(db, clinic_id, title, source_type, content)
            created += 1
    return created


async def main(clinic_slug: str) -> None:
    async with session_factory()() as db:
        clinic = await db.scalar(select(Clinic).where(Clinic.slug == clinic_slug, Clinic.name == "Aves Dental Clinic"))
        if clinic is None:
            raise SystemExit("Aves Dental Clinic with that slug was not found")
        count = await seed_aves_knowledge(db, clinic.id)
        print(f"Created {count} pending demo knowledge documents for {clinic.name}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optionally seed fictional Aves clinic knowledge")
    parser.add_argument("--clinic-slug", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.clinic_slug))
