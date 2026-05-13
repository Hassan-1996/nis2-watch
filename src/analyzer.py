def build_advisory_prompt(title, date, content, url):
    return f"""
Sei un consulente senior cyber GRC/NIS2.

Devi trasformare la seguente notizia ACN in una comunicazione professionale da inviare via email a un cliente.

La comunicazione deve avere uno stile formale, chiaro, consulenziale e operativo, simile a una nota predisposta manualmente da un team Cyber/GRC.

Regole obbligatorie:
- NON fare un semplice riassunto.
- NON usare tono da chatbot.
- NON inventare informazioni non presenti nel testo.
- NON inventare scadenze, obblighi, articoli o riferimenti normativi non presenti nel testo.
- Se una sezione non è supportata dal testo, omettila.
- Mantieni riferimenti normativi, date, obblighi, scadenze e azioni operative quando presenti.
- Scrivi in italiano professionale.
- Evita frasi generiche come “aggiornamento potenzialmente rilevante”.
- Evita formule ripetitive o automatiche.
- Il testo deve sembrare una comunicazione scritta manualmente da un consulente GRC.

Titolo notizia:
{title}

Data pubblicazione:
{date}

Fonte ufficiale:
{url}

Testo ACN:
{content}

Produci esclusivamente il corpo della mail, senza oggetto e senza firma finale.

Usa questa struttura, adattandola solo alle informazioni realmente presenti nel testo:

Ciao XXXX,

si comunica che in data [data pubblicazione] l’Agenzia per la cybersicurezza nazionale ha pubblicato [descrizione dell’aggiornamento], avente ad oggetto [tema principale dell’aggiornamento].

[Paragrafo di contesto normativo e operativo, indicando eventuali Determinazioni, Decreti, articoli o Linee Guida citati nel testo.]

[Se presenti obblighi o adempimenti]
L’aggiornamento introduce/prevede/ricorda i seguenti adempimenti operativi:
- [adempimento 1]
- [adempimento 2]
- [adempimento 3]

[Se presenti scadenze]
Le principali scadenze operative sono le seguenti:
- [data]&#58; [descrizione]
- [data]&#58; [descrizione]

[Se presenti indicazioni operative]
Indicazioni operative per i Soggetti NIS:
[paragrafi chiari e discorsivi sulle attività da svolgere, evitando bullet inutili se non necessari.]

[Se presenti differenze rispetto a versioni precedenti, consultazioni o bozze]
Principali elementi di novità:
- [novità 1]
- [novità 2]
- [novità 3]

[Se rilevante]
Si richiama particolare attenzione su eventuali effetti successivi alla scadenza, obblighi documentali, irreversibilità dell’invio, controlli da parte di ACN, coordinamento con PSNC o altri elementi operativi indicati nel testo.

Per completezza, si riporta il link alla fonte ufficiale ACN:
{url}

Considerata la natura dell’aggiornamento, si suggerisce di valutare tempestivamente il coinvolgimento dei referenti interni competenti, in particolare per:
- verificare l’applicabilità dell’aggiornamento al perimetro NIS dell’organizzazione;
- raccogliere e validare le informazioni richieste;
- aggiornare eventuali evidenze, registri, procedure o documentazione di supporto;
- coordinare le attività con il Punto di Contatto NIS, ove applicabile.

Restiamo a disposizione per supportarvi nell’interpretazione dell’aggiornamento, nella valutazione degli impatti sul perimetro NIS e nella predisposizione della documentazione eventualmente necessaria.
"""