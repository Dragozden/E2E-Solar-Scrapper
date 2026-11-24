"""Standalone loopback-only specification review pilot."""
from pathlib import Path
import os
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))


def main():
    import streamlit as st
    from dashboard.spec_review_admin import (QUEUE,FIELDS,load_catalog,list_jobs,load_review,folder_for,
        blocker,fingerprint,approve,read,report_summary,preferred_report,filter_catalog,report_message,CANDIDATE_STATUSES)
    st.set_page_config(page_title='Solar | Specification Review',layout='wide')
    # This process must be started explicitly on loopback; never mount it in public app.
    if (st.get_option('server.address')!='127.0.0.1' or not st.get_option('server.enableXsrfProtection') or not st.get_option('server.enableCORS')):
        st.error('Start only on 127.0.0.1 with XSRF and CORS protection enabled.'); st.stop()
    enabled=os.getenv('SOLAR_REVIEW_ENABLE_WRITE')=='1'
    st.title('Specification Review')
    st.caption('Local administrator pilot • '+('WRITE ENABLED' if enabled else 'READ ONLY'))
    if enabled: st.warning('Local trusted operator only. Stop the app after review; no authentication is provided.')
    try:
        rows=load_catalog(); jobs=list_jobs()
    except Exception as exc:
        st.error('Cannot load catalog / queue: '+type(exc).__name__); st.stop()
    by_url={r['source_url']:r for r in rows}
    cols=st.columns(4)
    for col,label,n in zip(cols,['PASS','INCOMPLETE / REVIEW','NOT_ENRICHED','Local documents'],[
        sum(r['status']=='PASS' for r in rows),sum(r['status'] in ('INCOMPLETE','REVIEW') for r in rows),
        sum(r['status']=='NOT_ENRICHED' for r in rows),len(jobs)]): col.metric(label,n)
    with st.expander('Current catalog and effective approvals'):
        statuses=sorted({r['status'] for r in rows})
        selected=st.multiselect('Technical status',statuses,default=statuses)
        query=st.text_input('Search title, model or URL')
        filtered=filter_catalog(rows,selected,query)
        st.caption(f'{len(filtered)} of {len(rows)} products')
        st.dataframe([{k:r[k] for k in ('rank','title','model','status','source','approval_id','method','pdf_stc_quality','issues')} for r in filtered],use_container_width=True)
    if not jobs: st.info('No local queue documents found.'); return
    summaries={}
    for j in jobs:
        for name in j['reports']:
            try: summaries[j['key'],name]=report_summary(QUEUE,j['key'],name)
            except (ValueError,OSError,TypeError): summaries[j['key'],name]={'status':'UNREADABLE','reasons':[]}
    def preference(j):
        states=[summaries[j['key'],n]['status'] for n in j['reports']]
        candidate=any(state in CANDIDATE_STATUSES for state in states)
        approved=by_url.get(j['source_url'],{}).get('approval_id') is not None
        return (candidate, approved)
    jobs=sorted(jobs,key=preference,reverse=True)
    job=st.selectbox('Document',jobs,format_func=lambda j:f"{j['model']} — {j['key']} — {by_url.get(j['source_url'],{}).get('status','NOT IN CATALOG')}")
    if not job['reports']: st.warning('No report available.'); return
    info={n:summaries[job['key'],n] for n in job['reports']}
    preferred=preferred_report(job['reports'],info)
    name=st.selectbox('Report',job['reports'],index=job['reports'].index(preferred),key='report_'+job['key'],format_func=lambda n:f"{n} — {info[n]['status']}")
    summary=info[name]
    try:
        review=load_review(QUEUE,job['key'],name)
        c=review.candidate; row=by_url[c.source_url]
        reason=blocker(review,row)
        stamp=fingerprint(review,row)
        pdf=read(folder_for(QUEUE,job['key'])/'document.pdf',20*1024*1024)
        if hashlib.sha256(pdf).hexdigest()!=c.pdf_sha256: raise ValueError('PDF_CHANGED')
    except Exception as exc:
        st.warning(report_message(summary))
        st.write('Report status:',summary['status'])
        if summary['reasons']: st.write('Parser diagnostics:',summary['reasons'])
        st.caption('Validation: '+type(exc).__name__)
        return
    st.subheader(row['title']); st.write(f'{c.model} • {c.power_w} W • page {c.pdf_page} • column {c.variant_column+1}')
    st.write('Method:',review.method); st.write('Current status:',row['status'])
    table=[{'Parameter':k,'Current Gold':row[k],'Candidate STC':c.values_stc[k]} for k in FIELDS]
    if review.ocr is not None:
        from scripts.reconstruct_panel_pdf_ocr import decode
        raw=read(folder_for(QUEUE,job['key'])/name,128*1024)
        if hashlib.sha256(raw).hexdigest()!=c.review_sha256: st.error('Review changed; refresh.'); return
        tokens=decode(raw)['selected_tokens']
        for entry in table: entry['OCR confidence']=round(tokens[entry['Parameter']]['confidence'],1)
    st.dataframe(table,use_container_width=True)
    st.write('HTML issues:',row['issues']); st.write('PDF source URL:',review.pdf_url)
    st.code(c.pdf_sha256,language=None)
    st.download_button('Open original PDF (download)',pdf,file_name='document.pdf',mime='application/pdf')
    if reason: st.info(reason); return
    if not enabled: st.info('Read-only mode. Approval disabled.'); return
    with st.form('confirm_'+stamp):
        typed=st.text_input('Type exact model')
        visual=st.checkbox('I visually checked the original PDF, revision, model, STC column and all six values.')
        submit=st.form_submit_button('Approve STC (append-only)')
    if submit:
        try:
            result=approve(QUEUE,job['key'],name,expected=stamp,confirm_model=typed,confirm_visual=visual,write_enabled=enabled)
            st.success(f"Approval {result['approval_id']} saved. Gold: {result['status']}. Refresh to see updated catalog.")
        except Exception as exc: st.error('Approval not completed: '+type(exc).__name__+'; refresh and check the local logs/database.')

if __name__=='__main__': main()
