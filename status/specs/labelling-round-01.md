# T56 labelling round 1 — eleven adverts

The subset was decided cold on 2026-08-25 and is **closed**: these five dimensions and no
others. `extraction_macro_f1` will be the mean over exactly these, with the other twenty
named in `dimensions_below_floor`.

These eleven adverts are a greedy cover of the five. Worked in order they take every one
of them to ten labels with no shortfall — that is the whole round, not a first instalment.

| dimension | | held | needed | rungs |
|---|---|---|---|---|
| `remote_arrangement` | Remote arrangement | 1 | 9 | **0** On-site · **0.5** Hybrid · **1** Fully remote |
| `compensation_transparency` | Pay transparency | 1 | 9 | **0** Silent on pay · **0.2** Described, never quantified · **0.9** A figure or a band |
| `contract_stability` | Contract stability | 1 | 9 | **0** Freelance / self-employed · **0.3** Fixed-term · **0.9** Open-ended |
| `schedule_flexibility` | Schedule flexibility | 1 | 9 | **0** Fixed timetable · **0.4** Some give · **0.7** Shaped around the person |
| `seniority_expectation` | Seniority expectation | 1 | 9 | **0.2** Junior · **0.5** Mid-level · **0.8** Senior |

### How to answer

Each advert below has one note box. Write one line per dimension, using this shorthand —
it transcribes into `Label` rows without anyone guessing what you meant:

```
remote      confirm
pay         change 0.0        the figure is a maximum tarifa, not a salary
contract    delete            that quote is about the client's contract, not the role's
hours       new 0.7  "horari flexible de matí"
seniority   absent            the advert genuinely does not say
```

* **confirm** — the proposed value is right. Recorded as `source: confirmed`.
* **change `<value>`** — right dimension, wrong rung. Recorded as `source: edited`.
* **delete** — the quote does not evidence this dimension at all. No label is written.
* **new `<value>` "quote"** — the marks missed it. Quote **verbatim** from the advert so
  the span can be located. Recorded as `source: human`.
* **absent** — the advert says nothing about it. No label; this is not the same as
  `delete`, and neither is the same as a `0` rung, which is a positive statement that the
  advert says *on-site* or *fixed hours*.

Add `negated` to any line where the advert **denies** the dimension ("sense guàrdies",
"no es requereix experiència") rather than being silent. That distinction is a separate
measurement (T59) and it cannot be recovered later from the value alone.

### What is deliberately not here

* **No cue data.** No patterns, no cue values, no highlighting derived from them. Marks
  come from the read pass in `suggestions.json`, whose provenance is recorded. A labeller
  confirming cue output would make the gate score the extractor against itself (D-2).
* **Marks for the other twenty dimensions are omitted**, though several of these adverts
  carry them. The round is the five.
* **The 32 `blind_control` adverts are not here.** They are unmarked on purpose so blind
  agreement can be read against confirmed agreement — a different measurement, not cheap
  labels.

---

## 1. CAMBRER/A DE PIS (HOSTALERIA)

`feinaactiva-09202623654` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/09202623654)

| dimension | id | proposed | quote |
|---|---|---|---|
| Contract stability | `contract_stability` | **0.9** Open-ended | “Tipus de contracte: LABORAL INDEFINIT” |
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “HORARI DE 9H A 17H, DOS DIES SETMANALS ROTATIUS DE DESCANS” |
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salari brut anual 20.184,34 euros (12 pagues).” |
| Seniority expectation | `seniority_expectation` | **0.2** Junior | “Experiència 12 mesos. Experiència com a cambrer/a de pis” |
| Remote arrangement | `remote_arrangement` | **0** On-site | “hotel a la localitat d´ALELLA” |


**The advert, verbatim**

> Cambrer/a de pis per a hotel a la localitat d´ALELLA
> Tipus de contracte: LABORAL INDEFINIT
> Horari: HORARI DE 9H A 17H, DOS DIES SETMANALS ROTATIUS DE DESCANS
> Salari brut anual 20.184,34 euros (12 pagues).
>
> neteja, ordre i posada a punt de les habitacions i zones comunes asignades. Reposició d´amenities, roba de llit, tovalloles i altres materials necessaris.
> Verificació de l´estat de les habitacions i comunicació d´incidències al departament corresponent.
> Manteniment de l´ordre als office de planta i control del material assignat
>
> Experiència 12 mesos. Experiència com a cambrer/a de pis
>
> Contracte laboral indefinit
>
> Jornada completa
>
> Salari mensual brut 1416
>
> Altres dades d'interès: Horari: 9 a 17 h

---

## 2. DevOps Junior (inglés B2) - Teletrabajo

`tecnoempleo-6bb2174bf25ab3f49b4c` · es · [source](https://www.tecnoempleo.com/devops-junior-ingles-b2-teletrabajo-second-window/github-actions-docker/rf-6bb2174bf25ab3f49b4c)

| dimension | id | proposed | quote |
|---|---|---|---|
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salario 28.000 brutos anuales.” |
| Remote arrangement | `remote_arrangement` | **1** Fully remote | “Modalidad 100 remoto” |
| Seniority expectation | `seniority_expectation` | **0.5** Mid-level | “con al menos 1-2 años de experiencia laboral en el rol (no se valoraran perfiles sin experiencia)” |
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “Horario estándar de oficina” |
| Contract stability | `contract_stability` | **0.9** Open-ended | “Contrato Indefinido” |


**The advert, verbatim**

> Desde Second Window buscamos un perfil de Ingeniero o Tecnico DevOps Junior con al menos 1-2 años de experiencia laboral en el rol (no se valoraran perfiles sin experiencia) para incorporarse a una compañía consolidada a nivel internacional en un puesto muy estable 100 remoto y a largo plazo. Al tratarse de un puesto estable se busca una persona que también quiera esa estabilidad al menos a medio-largo plazo. Es necesario un nivel de inglés medio-alto (al menos B2). SKILLS NECESARIAS Herramientas CI/CD con estrategias de Ramificación (Github Actions) Orquestadores Docker (Kubernetes PaaS Openshift) Conocimiento de los servicios de Cloud en los principales proveedores de Cloud Pública (AWS o Azure) Nivel de inglés B2 Actitud proactiva y resolutiva Qué ofrece el proyecto Contrato Indefinido Salario 28.000 brutos anuales. Modalidad 100 remoto Horario estándar de oficina Beneficios sociales seguro médico seguro de vida plan de formación ticket restaurante... Si estas buscando una nueva oportunidad no dudes en aplicar y te informaremos al respecto

---

## 3. Angular  V14 Developer. Teletrabajo 100

`tecnoempleo-ac7416da82c8f3897a4f` · es · [source](https://www.tecnoempleo.com/angular-v14-developer-teletrabajo-100-second-windo/angular/rf-ac7416da82c8f3897a4f)

| dimension | id | proposed | quote |
|---|---|---|---|
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salario Competitivo Banda salarial entre 28.000 y 30.000 brutos anuales (según experiencia aportada).” |
| Remote arrangement | `remote_arrangement` | **1** Fully remote | “Teletrabajo 100 Trabaja cómodamente desde donde quieras.” |
| Schedule flexibility | `schedule_flexibility` | **0.7** Shaped around the person | “Disponibilidad horaria en jornada flexible (Madrid entre las 800 y las 1800 h).” |
| Seniority expectation | `seniority_expectation` | **0.5** Mid-level | “Experiencia demostrable de al menos 3 a 4 años en desarrollo con Angular (v14).” |
| Contract stability | `contract_stability` | **0.9** Open-ended | “Estabilidad Real Contrato indefinido desde el primer día para que construyas tu futuro con nosotros.” |


**The advert, verbatim**

> En Second Window seguimos ampliando nuestro equipo tecnológico. Actualmente estamos buscando un/a Desarrollador/a Angular 14 con capacidad de análisis y diseño técnico para sumarse a un proyecto de mantenimiento y nuevos desarrollos en el sector de la Administración Pública (AAPP). Si tienes experiencia creando interfaces robustas dominio del ecosistema web moderno y buscas la comodidad de un entorno completamente remoto queremos conocerte Cuáles serán tus funciones principales Como Frontend Engineer / Analista Programador Angular Desarrollo y Mantenimiento Diseñar implementar y mantener aplicaciones web utilizando Angular v14 TypeScript y JavaScript. Análisis y Diseño Técnico Participar activamente en la toma de requerimientos análisis funcional y arquitectura de componentes técnicos para soluciones de la Administración Pública. Calidad y Buenas Prácticas Garantizar un código limpio escalable y mantenible siguiendo patrones de diseño modernos. Soporte Full-Stack (Deseable) Colaborar en la capa backend con Java cuando el proyecto lo requiera (perfil Fullstack Angular / Java). Qué buscamos en ti Requisitos mínimos Experiencia demostrable de al menos 3 a 4 años en desarrollo con Angular (v14). Sólidos conocimientos en TypeScript JavaScript HTML5 y CSS3. Valorable capacidad de análisis y diseño técnico. Disponibilidad horaria en jornada flexible (Madrid entre las 800 y las 1800 h). Deseable Experiencia o conocimientos backend en Java (Spring / Spring Boot). Experiencia previa en proyectos para la Administración Pública (AAPP). Qué te ofrecemos en Second Window Teletrabajo 100 Trabaja cómodamente desde donde quieras. Estabilidad Real Contrato indefinido desde el primer día para que construyas tu futuro con nosotros. Salario Competitivo Banda salarial entre 28.000 y 30.000 brutos anuales (según experiencia aportada). Bienestar Integral Seguro médico privado y seguro de vida cubiertos al 100 por la empresa. Optimización Salarial Acceso a nuestra plataforma de Retribución Flexible para maximizar tu sueldo neto (Tickets Restaurante Guardería y Tarjeta Transporte). Tu Tiempo es Sagrado 23 días de vacaciones anuales + el día de tu cumpleaños totalmente libre para que lo celebres como quieras. Crecimiento a tu Medida Plan de carrera personalizado y acceso continuo a formación técnica para que nunca dejes de aprender. Te entusiasma el reto Si crees que tu perfil encaja con esta posición de Angular Specialist / Front-End Developer y quieres dar el siguiente gran paso en tu carrera queremos conocerte

---

## 4. INFERMER/A  DE CURES

`feinaactiva-09202621892` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/09202621892)

| dimension | id | proposed | quote |
|---|---|---|---|
| Contract stability | `contract_stability` | **0.9** Open-ended | “Contracte indefinit amb horari de torns.” |
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “I un cap de setmana cada tres en torn a convenir amb l'empresa.” |
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salari mensual brut 1985” |
| Seniority expectation | `seniority_expectation` | **0.2** Junior | “Experiència prèvia 12 mesos en tasques similars.” |


No mark was proposed for: `remote_arrangement`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Es cerca un/a diplomat/da universitari en infermeria. Contracte indefinit amb horari de torns. Dos dies matí: 7.30h. a 14h i dos dies tardes: 14.30h. a 21h. I un cap de setmana cada tres en torn a convenir amb l'empresa. Nivell intermedi de català i castellà.
>
> Atenció integral usuari, tasques assistencials: cures, glicèmies, seguiment nous ingressos, coordinació amb els equips, seguiment protocols. Empatia i tracte proper, formació contínua. Experiència prèvia 12 mesos en tasques similars. Habilitats en la gestió i coordinació d'equips de treball.
>
> Experiència 12 mesos. Valorable, infermers/es de cures.
>
> diplomatura o enginyeria tècnica - infermeria
>
> català (parlat Mitjà, escrit Mitjà)
>
> espanyol (parlat Mitjà, escrit Mitjà)
>
> Contracte laboral indefinit
>
> Jornada intensiva
>
> Salari mensual brut 1985

---

## 5. TÈCNICS/TÈCNIQUES EN SOPORT INFORMÀTIC

`feinaactiva-09202624157` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/09202624157)

| dimension | id | proposed | quote |
|---|---|---|---|
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Sou: 1.928€ bruts X 14 pagues” |
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “Horari: de DLL-DJ de 09:00 a 14:00 i de 15:00 a 18:20; DV de 08:00 a 15:00 hores” |
| Seniority expectation | `seniority_expectation` | **0.5** Mid-level | “Experiència en l’ocupació: 24 mesos de suport IT de Nivell 2” |
| Contract stability | `contract_stability` | **0.9** Open-ended | “Tipus de contracte: Indefinit” |


No mark was proposed for: `remote_arrangement`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Titulacions: TÈCNICS SUPERIORS EN ADMINISTRACIÓ DE SISTEMES INFORMÀTICS EN XARXA
> Experiència en l’ocupació: 24 mesos de suport IT de Nivell 2 (hardware i software)
> Idiomes: ANGLÈS
> Tipus de contracte: Indefinit
> Horari: de DLL-DJ de 09:00 a 14:00 i de 15:00 a 18:20; DV de 08:00 a 15:00 hores
> Sou: 1.928€ bruts X 14 pagues
>
> Entorn tecnològic:
> Windows Server (Active Directory, DNS, DHCP, PowerShell i polítiques de grup)
> SQL Server (consultes, índexs, manteniment, informes i replicació)
> Virtualització (VMware i Hyper-V)
> Servidors web (IIS)
> Xarxes i resolució d’incidències (protocols, seguretat, IPv4/IPv6, VLAN, tallafocs)
>
> Oferta de treball per a la contractació de persones amb discapacitat
>
> -Seguiment i gestió dels tiquets assignats fins a la seva resolució completa.
> -Documentació d'incidències i solucions a la base de coneixement.
> -Connexió remota als sistemes daparcament per a la resolució d'incidències.
> -Configuració i actualització remota d'aplicacions.
> -Participació en projectes d'implantació i integració d'aplicacions.
> -Suport remot a filials d'àmbit internacional.
>
> Experiència 24 mesos. 24 mesos de suport IT de Nivell 2 (hardware i software)
>
> anglès (parlat Mitjà, escrit Mitjà)
>
> Contracte laboral indefinit
>
> Jornada completa
>
> Salari mensual brut 1928

---

## 6. BACKEND DEVELOPER (H/D) - JAVA

`feinaactiva-FA92317378` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/FA92317378)

| dimension | id | proposed | quote |
|---|---|---|---|
| Remote arrangement | `remote_arrangement` | **1** Fully remote | “- Més del 50% de la jornada de teletreball.” |
| Schedule flexibility | `schedule_flexibility` | **0.7** Shaped around the person | “- Flexibilitat horària.” |
| Pay transparency | `compensation_transparency` | **0.2** Described, never quantified | “- Retribució competitiva, adequada a l'experiència i habilitats.” |
| Seniority expectation | `seniority_expectation` | **0.5** Mid-level | “Entre 3 i 5 anys d'experiència desenvolupant tasques similars” |


No mark was proposed for: `contract_stability`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> AXXON selecciona BACKEND DEVELOPER (H/D), especialitzat en JAVA, per a consultoria tecnològica líder en el seu sector, ubicada a Girona.
>
> S'ofereix:
> - Estabilitat laboral.
> - Flexibilitat horària.
> - Més del 50% de la jornada de teletreball.
> - Retribució competitiva, adequada a l'experiència i habilitats.
> - Entorn de treball jove, dinàmic i multidisciplinar.
> - Formació i Certificacions tècniques.
> - Innovació, últimes tecnologies i versions.
>
> - Analitzar, dissenyar i desenvolupar noves aplicacions.
> - Contribuir a totes les fases del cicle de vida del desenvolupament, aplicant metodologia AGILE.
> - Assegurar l'adaptació dels canvis amb les especificacions del client.
> - Preparar i produir versions de components de software.
> - Donar suport a la millora continua a través de la investigació de noves alternatives i tecnologies.
>
> Experiència 3 anys. Entre 3 i 5 anys d'experiència desenvolupant tasques similars a les descrites, treballant amb Java.
>
> Enginyeria informàtica i/o CFGS DAM / DAW.
>
> Competències / coneixements: - Nivell B2 d'anglès.
> - Java.
> - Hibernate.
> - Java Spring boot.
>
> Contracte laboral indefinit
>
> Jornada intensiva

---

## 7. FISIOTERAPEUTA

`feinaactiva-FA92318249` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/FA92318249)

| dimension | id | proposed | quote |
|---|---|---|---|
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salari mensual brut des de '900' fins a '1000'” |
| Remote arrangement | `remote_arrangement` | **0** On-site | “per cobrir l'atenció dels nostres dos centres de gent gran situats al barri de La Bordeta (Lleida)” |
| Seniority expectation | `seniority_expectation` | **0.2** Junior | “Es valorarà experiència en el sector de residències i centres de dia.” |
| Contract stability | `contract_stability` | **0.9** Open-ended | “Contracte laboral indefinit” |


No mark was proposed for: `schedule_flexibility`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Busquem un/a fisioterapeuta compromès/a i amb vocació per cobrir l'atenció dels nostres dos centres de gent gran situats al barri de La Bordeta (Lleida).
>
> La seva missió principal serà millorar la qualitat de vida, la mobilitat i l'autonomia dels nostres residents, dissenyant i executant tractaments personalitzats.
>
> - Avaluació inicial i seguiment de l'estat físic i funcional dels residents.
> - Disseny i aplicació de plans de tractament individuals.
> - Realització de sessions de psiciomotricitat.
> - Prevenció de la pèrdua de mobilitat i tractament del dolor crònic.
> - Coordinació amb l'equip interdisciplinari (metges/esses, infermeria, psicologia i TASOC) per al benestar integral de l'usuari.
> - Assessorament a les famílies i a l'equip de auxiliars sobre mobilitzacions i transferències segures.
>
> Experiència 1 anys. Es valorarà experiència en el sector de residències i centres de dia.
>
> TÍTOL DE GRAU
>
> Contracte laboral indefinit
>
> Jornada parcial (20 hores - jornada setmanal)
>
> Salari mensual brut des de '900' fins a '1000'

---

## 8. DEPENDIENTES/TAS DE POLLERÍA

`feinaactiva-FA92318324` · es · [source](https://feinaactiva.gencat.cat/search/offers/detail/FA92318324)

| dimension | id | proposed | quote |
|---|---|---|---|
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “De martes a sábado por la mañana, viernes mañana y tarde..” |
| Remote arrangement | `remote_arrangement` | **0** On-site | “para mercado Municipal de Ripollet y Cerdanyola” |
| Seniority expectation | `seniority_expectation` | **0.5** Mid-level | “Experiencia en el sector del pollo, atención al cliente, deshuesar etc...” |
| Contract stability | `contract_stability` | **0.9** Open-ended | “Contracte laboral indefinit” |


No mark was proposed for: `compensation_transparency`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Se busca 2 dependientes/tas de polleria para mercado Municipal de Ripollet y Cerdanyola empresa polleria Román
>
> Elaboración , deshuesar, atención al cliente..etc...
>
> Experiència 1 anys. Experiencia en el sector del pollo, atención al cliente, deshuesar etc...
>
> català (parlat Mitjà, escrit Mitjà)
>
> Contracte laboral indefinit
>
> Jornada intensiva
>
> Altres dades d'interès: De martes a sábado por la mañana, viernes mañana y tarde..

---

## 9. TÉCNICO/CA FISCAL CONTABLE

`feinaactiva-FA92318785` · es · [source](https://feinaactiva.gencat.cat/search/offers/detail/FA92318785)

| dimension | id | proposed | quote |
|---|---|---|---|
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salario bruto anual: entorno a 35 K b/a según experiencia.” |
| Remote arrangement | `remote_arrangement` | **0.5** Hybrid | “Modelo presencial con 1 día de teletrabajo semanal.” |
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “Horario: 9h-14h /15h-18.30h de L a J y 9h-14h V.” |
| Seniority expectation | `seniority_expectation` | **0.5** Mid-level | “Experiencia como Asesor Fiscal en despacho o asesoría.” |


No mark was proposed for: `contract_stability`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Buscamos UN/A ASESOR/A como responsable de ofrecer asesoramiento tributario integral a los clientes del despacho, con un foco especial en Personas Físicas, incluyendo la planificación fiscal, el cumplimiento de obligaciones y la optimización de su situación patrimonial. Además, dará soporte en el análisis y preparación de impuestos como IRPF e Impuesto sobre Sociedades (IS), garantizando rigor técnico, atención personalizada y un acompañamiento continuo al cliente.
>
> 1. Asesoramiento a Personas Físicas (PF):
> -Planificación fiscal individualizada para clientes de renta alta, profesionales liberales y particulares.
> -Preparación, revisión y presentación de declaraciones de IRPF, patrimonio, plusvalías, no residentes, donaciones y otros tributos relacionados.
> -Revisión del impacto fiscal de inversiones, alquileres, herencias o reestructuraciones patrimoniales.
> -Optimización fiscal y recomendaciones proactivas.
>
> 2. Impuesto sobre la Renta de las Personas Físicas (IRPF):
> -Elaboración y gestión integral de la campaña del IRPF.
> -Análisis de deducciones, reducciones y beneficios fiscales aplicables.
> -Cálculo y revisión de rendimientos del trabajo, actividades económicas, capital mobiliario e inmobiliario.
> -Gestión de requerimientos o inspecciones relacionadas con IRPF.
>
> 3. Impuesto sobre Sociedades (IS):
> -Apoyo en el cierre fiscal y revisión de deducibilidad de gastos.
> -Análisis de operaciones vinculadas y su documentación cuando sea necesario.
> -Coordinación con contabilidad para cuadrar datos fiscales y contables.
>
> 4. Relación con Clientes y Administración:
> -Atención directa y continuada al cliente, ofreciendo un servicio cercano y resolutivo.
> -Gestión de trámites ante la Agencia Tributaria: requerimientos, inspecciones, reposiciones y recursos.
> -Explicación clara y comprensible de escenarios fiscales y alternativas legales.
>
> 5. Actualización y Cumplimiento Normativo:
> -Mantenerse actualizado en normativa tributaria estatal y autonómica.
> -Velar por el cumplimiento riguroso de las obligaciones fiscales del cliente.
>
> Experiència 2 anys. Experiencia como Asesor Fiscal en despacho o asesoría.
>
> Competències / coneixements: Grado Superior Administración y Finanzas o similar.
>
> Contracte laboral indefinit
>
> Jornada completa
>
> Altres dades d'interès: Horario: 9h-14h /15h-18.30h de L a J y 9h-14h V.
> Modelo presencial con 1 día de teletrabajo semanal.
> Salario bruto anual: entorno a 35 K b/a según experiencia.

---

## 10. EDUCADORS/ES AMBIENTALS CAMPANYA DE COMUNICACIÓ COMARCA DEL SEGRIÀ

`feinaactiva-FA92319865` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/FA92319865)

| dimension | id | proposed | quote |
|---|---|---|---|
| Pay transparency | `compensation_transparency` | **0.9** A figure or a band | “Salari mensual brut 1500” |
| Schedule flexibility | `schedule_flexibility` | **0** Fixed timetable | “Jornada completa de dilluns a divendres, o de dimarts a dissabte. Disponibilitat per treballar algun dissabte -” |
| Contract stability | `contract_stability` | **0.3** Fixed-term | “Durada del contracte: entre 6-7 mesos, com a mínim.” |
| Contract stability | `contract_stability` | **0.3** Fixed-term | “Contracte: fix discontinu” |
| Remote arrangement | `remote_arrangement` | **0** On-site | “• Flexibilitat i adaptació al treball de carrer.” |
| Remote arrangement | `remote_arrangement` | **0** On-site | “Informació per a la implantació del nou servei de recollida de residus en 15 municipis del al Segrià” |


No mark was proposed for: `seniority_expectation`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Informació per a la implantació del nou servei de recollida de residus en 15 municipis del al Segrià
>
> - Informació a ciutadania i activitats econòmiques sobre la implantació del nou servei de recollida de residus basat en un model de contenidors tancats i porta a porta comercial, abans i desprès de la implantació, atenent les Oficines de REsidus municipals.
> - Accions de sensibilització a paradistes de mercats municipals.
> - Realització de segones visites personalitzades a activitats econòmiques per al repartiment i associació dels materials necessaris per a la implantació del nou servei, amb lliurament d’albarà i registre corresponent.
> - Preparació i lliurament dels materials a la ciutadania, les activitats econòmiques i els equipaments (cubells, targetes, etc.).
> - Control de l' estoc dels materials que cal distribuir.
> - Fer un seguiment intensiu del porta a porta comercial i als punts de contenidors durant els primers mesos d’introducció dels nous serveis amb reforç comunicatiu on hi hagi punts sensibles.
> - Col·laborar (si s'escau) en la logística, trasllat i emmagatzematge de materials i realització de l’oficina de residus i punts informatius.
> - Suport logístic de les reunions informatives especifiques adreçades a diferents col·lectius, incloent-hi el muntatge i la preparació, i desmuntatge de l'espai.
> - Detecció, comunicació i seguiment d’incidències relacionades amb el servei.
> - Atenció ciutadana (telèfon, correu electrònic, etc.)
> - Reunions de coordinació internes.
> - Altres activitats relacionades.
>
> Experiència 6 mesos. En campanyes de comunicació i/o informació i/o atenció al públic, o bé en tasques relacionades amb el sector.
>
> TÍTOL FP DE GRAU MIG
>
> català (parlat Superior, escrit Superior)
>
> espanyol (parlat Superior, escrit Superior)
>
> Competències / coneixements: FP i/o estudis universitaris relacionats amb l’educació ambiental, les ciències ambientals, l’educació social, la pedagogia o similars.
>
> Disponibilitat de vehicle
>
> Permisos de conduir: b
>
> Contracte laboral temporal (6 mesos)
>
> Jornada completa
>
> Salari mensual brut 1500
>
> Altres dades d'interès: Durada del contracte: entre 6-7 mesos, com a mínim.
> Incorporació mitjans d'agost.
> Jornada completa de dilluns a divendres, o de dimarts a dissabte. Disponibilitat per treballar algun dissabte -
> Tipus: presencial,
> Contracte: fix discontinu
> Pagament de quilometratge + incentius extra a finalització de fases
>
> Es valorarà experiència en:
> o Campanyes d’informació i sensibilització ambiental
> o Atenció ciutadana i treball de cara al públic
> o Implantació de serveis de recollida selectiva o gestió de residus
> o Visites a activitats econòmiques i treball de camp
> o Gestió de censos, bases de dades o registres
> o Coneixement de la gestió de residus municipals
>
> Habilitats:
> • Dinamisme i proactivitat.
> • Organització i autonomia
> • Capacitat de treballar en equip
> • Bona comunicació i assertivitat.
> • Flexibilitat i adaptació al treball de carrer.
> • Compromís.

---

## 11. MONITORS/ES CASALET TARDES BARCELONA

`feinaactiva-FA92317864` · ca · [source](https://feinaactiva.gencat.cat/search/offers/detail/FA92317864)

| dimension | id | proposed | quote |
|---|---|---|---|
| Contract stability | `contract_stability` | **0.3** Fixed-term | “Contractació fins el 19 de juny en horari de 15,30 a 17 h.” |
| Seniority expectation | `seniority_expectation` | **0.2** Junior | “Experiència 3 mesos. Experiència en lleure, casals, menjadors escolars...amb infants d 'infantil i primaria.” |
| Remote arrangement | `remote_arrangement` | **0** On-site | “en una escola a Barcelona (zona Vallvidriera)” |


No mark was proposed for: `compensation_transparency`, `schedule_flexibility`. Say `new …` if the advert in fact states one.

**The advert, verbatim**

> Precisem incorporar a monitors/es per l'espai de lleure de 15,30 a 17 h. en una escola a Barcelona (zona Vallvidriera).
>
> Les tasques seran les pròpies d'un monitor de lleure: dinamitzar el grup a través de jocs i activitats i vetllar pel grup d'infants assignat.
>
> Experiència 3 mesos. Experiència en lleure, casals, menjadors escolars...amb infants d 'infantil i primaria.
>
> català (parlat Superior, escrit Superior)
>
> Contracte laboral temporal (1 mesos)
>
> Jornada parcial tarda (1 hores - jornada diaria)
>
> Altres dades d'interès: Contractació fins el 19 de juny en horari de 15,30 a 17 h.
> Possibilitat de fer després el Casal d'estiu en horaris entre les 9 i les 17 h. de dilluns a divendres.

---
