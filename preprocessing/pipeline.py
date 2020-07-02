import time
import os
from bs4 import BeautifulSoup
import sys
import json
import re
from multiprocessing import Pool
import multiprocessing
from bs4 import BeautifulSoup
import urllib3
http = urllib3.PoolManager()
urllib3.disable_warnings()
import copy
from shutil import copyfile
from nltk.tokenize import word_tokenize, sent_tokenize
import urllib.parse
output_folder = 'data'
input_htmls = 'htmls'

def tokenize(string, remmove_dot=False):
    def func(string):
        return " ".join(word_tokenize(string))
    
    string = string.rstrip('.')
    return func(string)

def url2dockey(string):
    string = urllib.parse.unquote(string)
    return string

def filter_firstKsents(string, k):
    string = sent_tokenize(string)
    string = string[:k]
    return " ".join(string)

def process_link(text):
    tmp = []
    hrefs = []
    for t in text.find_all('a'):
        if len(t.get_text().strip()) > 0:
            if 'href' in t.attrs and t['href'].startswith('/wiki/'):
                tmp.append(t.get_text().strip())
                hrefs.append(t['href'].split('#')[0])
            else:
                tmp.append(t.get_text().strip())
                hrefs.append(None)
    if len(tmp) == 0:
        return [''], [None]
    else:
        return tmp, hrefs

def remove_ref(text):
    for x in text.find_all('sup'):
        x.extract()
    return text

def get_section_title(r):
    text = r.previous_sibling
    title_hierarchy = []
    while text is None or text == '\n' or text.name not in ['h2', 'h3']:
        if text is None:
            break
        else:
            text = text.previous_sibling               
    
    if text is not None:
        title_hierarchy.append(text.find(class_='mw-headline').text)
        if text.name in ['h3']:
            while text is None or text == '\n' or text.name not in ['h2']:
                if text is None:
                    break
                else:
                    text = text.previous_sibling               

            if text is None:
                pass
            else:
                title_hierarchy.append(text.find(class_='mw-headline').text)
    
    if len(title_hierarchy) == 0:
        return ''
    else:
        tmp = ' -- '.join(title_hierarchy[::-1])
        return normalize(tmp)

def get_section_text(r):
    text = r.previous_sibling
    section_text = ''
    while text is not None:
        if text == '\n':
            text = text.previous_sibling
        elif text.name in ['h1', 'h2', 'h3', 'h4']:
            break
        else:
            tmp = text.text
            if tmp:
                mask = ['note', 'indicate', 'incomplete', 'source', 'reference']
                if  any([_ in tmp.lower() for _ in mask]):
                    tmp = ''
                else:
                    tmp = normalize(tmp)
                    if section_text:
                        section_text = tmp + ' ' + section_text
                    else:
                        section_text = tmp
            text = text.previous_sibling
    return section_text

def normalize(string):
    string = string.strip().replace('\n', ' ')
    return tokenize(string)

def harvest_tables(f_name):
    results = []
    with open(os.path.join(input_htmls, f_name), 'r') as f:
        soup = BeautifulSoup(f, 'html.parser')
        rs = soup.find_all(class_='wikitable sortable')
        
        for it, r in enumerate(rs):
            heads = []
            rows = []
            for i, t_row in enumerate(r.find_all('tr')):
                if i == 0:
                    for h in t_row.find_all(['th', 'td']):
                        h = remove_ref(h)
                        if len(h.find_all('a')) > 0:
                            heads.append(process_link(h))
                        else:
                            heads.append(([h.get_text().strip()], [None]))
                else:
                    row = []
                    for h in t_row.find_all(['th', 'td']):
                        h = remove_ref(h)
                        if len(h.find_all('a')) > 0:
                            row.append(process_link(h))
                        else:
                            row.append(([h.get_text().strip()], [None]))

                    if all([len(cell[0]) == 0 for cell in row]):
                        continue
                    else:
                        rows.append(row)
            
            rows = rows[:20]
            if any([len(row) != len(heads) for row in rows]) or len(rows) < 8:
                continue
            else:
                try:
                    section_title = get_section_title(r)
                except Exception:
                    section_title = ''
                try:
                    section_text = get_section_text(r)
                except Exception:
                    section_text = ''
                title = soup.title.string
                title = re.sub(' - Wikipedia', '', title)
                url = 'https://en.wikipedia.org/wiki/{}'.format('_'.join(title.split(' ')))
                uid = f_name[:-5] + "_{}".format(it)
                results.append({'url': url, 'title': title, 'header': heads, 'data': rows, 
                                'section_title': section_title, 'section_text': section_text,
                                'uid': uid})
    return results

def inplace_postprocessing(tables):
    deletes = []
    for i, table in enumerate(tables):
        # Remove sparse columns
        to_remove = []
        for j, h in enumerate(table['header']):
            if 'Coordinates' in h[0][0] or 'Image' in h[0][0]:
                to_remove.append(j)
                continue
            
            count = 0
            total = len(table['data'])
            for d in table['data']:
                #print(d[j])
                if d[j][0][0] != '':
                    count += 1
            
            if count / total < 0.5:
                to_remove.append(j)
        
        bias = 0
        for r in to_remove:
            del tables[i]['header'][r - bias]
            for _ in range(len(table['data'])):
                del tables[i]['data'][_][r - bias]
            bias += 1
        
        # Remove sparse rows
        to_remove = []
        for k in range(len(table['data'])):
            non_empty = [1 if _[0][0] != '' else 0 for _ in table['data'][k]]
            if sum(non_empty) < 0.5 * len(non_empty):
                to_remove.append(k)
        
        bias = 0
        for r in to_remove:        
            del tables[i]['data'][r - bias]
            bias += 1
        
        if len(table['header']) > 6:
            deletes.append(i)
        elif len(table['header']) <= 2:
            deletes.append(i)
        else:
            count = 0
            total = 0
            for row in table['data']:
                for cell in row:
                    if len(cell[0][0]) != '':
                        if cell[1] == [None]:
                            count += 1                    
                        total += 1
            if count / total >= 0.7:
                deletes.append(i)

    print('out of {} tables, {} need to be deleted'.format(len(tables), len(deletes)))

    bias = 0
    for i in deletes:
        del tables[i - bias]
        bias += 1

def get_summary(page):
    if page.startswith('https'):
        pass
    elif page.startswith('/wiki'):
        page = 'https://en.wikipedia.org{}'.format(page)
    else:
        page = 'https://en.wikipedia.org/wiki/{}'.format(page)
    
    r = http.request('GET', page)
    if r.status == 200:
        data = r.data.decode('utf-8')
        data = data.replace('</p><p>', ' ')        
        soup = BeautifulSoup(data, 'html.parser')

        div = soup.body.find("div", {"class": "mw-parser-output"})

        children = div.findChildren("p" , recursive=False)
        summary = 'N/A'
        for child in children:
            if child.get_text().strip() != "":
                html = str(child)
                html = html[html.index('>') + 1:].strip()
                if not html.startswith('<'):
                    summary = child.get_text().strip()
                    break
                elif html.startswith('<a>') or html.startswith('<b>') or \
                        html.startswith('<i>') or html.startswith('<a ') or html.startswith('<br>'):
                    summary = child.get_text().strip()
                    break
                else:
                    continue
        return summary
    elif r.status == 429:
        time.sleep(1)
        return get_summary(page)
    else:
        raise

def crawl_hyperlinks(inputs):
    table, index = inputs
    dictionary = {}
    for cell in table['header']:
        if cell[1]:
            for tmp in cell[1]:
                if tmp not in dictionary:                
                    try:
                        summary = get_summary(tmp)
                        dictionary[tmp] = summary
                    except Exception:
                        dictionary[tmp] = 'N/A'
        
    for row in table['data']:
        for cell in row:
            if cell[1]:
                for tmp in cell[1]:
                    if tmp not in dictionary:
                        try:
                            summary = get_summary(tmp)
                            dictionary[tmp] = summary
                        except Exception:
                            dictionary[tmp] = 'N/A'
    
    return dictionary

def summarize(table):
    tmp = '_'.join(table['title'].split(' '))
    name = '/wiki/{}'.format(tmp)
    try:
        summary = get_summary(table['url'])
    except Exception:
        summary = 'N/A'
    return name, summary

def clean_cell_text(string):
    string = string.replace('\n', ' ')
    string = string.rstrip('^')
    string = string.replace('\u200e', '')
    string = string.replace('\ufeff', '')
    string = string.replace('–', '-')
    string = string.replace(u'\u2009', u' ')
    string = string.replace(u'\u2010', u' - ')
    string = string.replace(u'\u2011', u' - ')
    string = string.replace(u'\u2012', u' - ')
    string = string.replace(u'\u2013', u' - ')
    string = string.replace(u'\u2014', u' - ')
    string = string.replace(u'\u2015', u' - ')
    string = string.replace(u'\u2018', u'')
    string = string.replace(u'\u2019', u'')
    string = string.replace(u'\u201c', u'')
    string = string.replace(u'\u201d', u'')
    string = re.sub(r' +', ' ', string)
    string = string.strip()
    return string


def tokenization_tab(f_n):
    if f_n.endswith('.json'):
        with open('{}/tables/{}'.format(output_folder, f_n)) as f:
            table = json.load(f)
        
        for row_idx, row in enumerate(table['data']):
            for col_idx, cell in enumerate(row):
                for i, ent in enumerate(cell[0]):
                    if ent:
                        table['data'][row_idx][col_idx][0][i] = tokenize(ent, True)
                    if table['data'][row_idx][col_idx][1][i]:
                        table['data'][row_idx][col_idx][1][i] = urllib.parse.unquote(table['data'][row_idx][col_idx][1][i])
        
        for col_idx, header in enumerate(table['header']):
            for i, ent in enumerate(header[0]):
                if ent:
                    table['header'][col_idx][0][i] = tokenize(ent, True)
                if table['header'][col_idx][1][i]:
                    table['header'][col_idx][1][i] = urllib.parse.unquote(table['header'][col_idx][1][i])

        with open('{}/tables_tok/{}'.format(output_folder, f_n), 'w') as f:
            json.dump(table, f, indent=2)

def tokenization_req(f_n):
    if f_n.endswith('.json'):
        with open('{}/{}/{}'.format(output_folder, 'request', f_n)) as f:
            request_document = json.load(f)

        for k, v in request_document.items():
            sents = tokenize(v)
            request_document[k] = sents

        with open('{}/request_tok/{}'.format(output_folder, f_n), 'w') as f:
            json.dump(request_document, f, indent=2)

def recover(string):
    string = string[6:]
    string = string.replace('_', ' ')
    return string
    
def clean_text(k, string):
    if "Initial visibility" in string:
        return recover(k)
    
    position = string.find("mw-parser-output")
    if position != -1:
        left_quote = position - 1
        while left_quote >= 0 and string[left_quote] != '(':
            left_quote -= 1
        right_quote = position + 1
        while right_quote < len(string) and string[right_quote] != ')':
            right_quote += 1
        
        string = string[:left_quote] + " " + string[right_quote + 1:]
        
        position = string.find("mw-parser-output")
        if position != -1:
            #print(string)
            right_quote = position + 1
            while right_quote < len(string) and string[right_quote] != '\n':
                right_quote += 1
            #print("----------------")
            string = string[:position] + string[right_quote + 1:]
            #print(string)
            #print("################")
    
    string = string.replace(u'\xa0', u' ')
    string = string.replace('\ufeff', '')
    string = string.replace(u'\u200e', u' ')
    string = string.replace('–', '-')
    string = string.replace(u'\u2009', u' ')
    string = string.replace(u'\u2010', u' - ')
    string = string.replace(u'\u2011', u' - ')
    string = string.replace(u'\u2012', u' - ')
    string = string.replace(u'\u2013', u' - ')
    string = string.replace(u'\u2014', u' - ')
    string = string.replace(u'\u2015', u' - ')
    string = string.replace(u'\u2018', u'')
    string = string.replace(u'\u2019', u'')
    string = string.replace(u'\u201c', u'')
    string = string.replace(u'\u201d', u'')    
    
    string = string.replace(u'"', u'')
    string = re.sub(r'[\n]+', '\n', string)
    
    string = re.sub(r'\.+', '.', string)
    string = re.sub(r' +', ' ', string)
    
    #string = re.sub(r"'+", "'", string)
    #string = string.replace(" '", " ")
    #string = string.replace("' ", " ")
    string = filter_firstKsents(string, 12)
    
    return string
    
if __name__ == "__main__":
    if len(sys.argv) == 2:
        steps = sys.argv[1].split(',')
    else:
        steps = ['1', '2', '3', '4', '5', '6']

    cores = multiprocessing.cpu_count()
    pool = Pool(cores)
    print("Initializing the pool of cores")

    if not os.path.exists(output_folder):
        os.mkdir(output_folder)
    if not os.path.exists('{}/tables'.format(output_folder)):
        os.mkdir('{}/tables'.format(output_folder))
    if not os.path.exists('{}/request'.format(output_folder)):
        os.mkdir('{}/request'.format(output_folder))
    
    if '1' in steps:
        # Step1: Harvesting the tables
        rs = pool.map(harvest_tables, os.listdir(input_htmls))
        tables = []
        for r in rs:
            tables = tables + r
        print("Step1: Finishing harvesting the tables")

    if '2' in steps:
        # Step2: Postprocessing the tables
        inplace_postprocessing(tables)
        with open('{}/processed_new_table_postfiltering.json'.format(output_folder), 'w') as f:
            json.dump(tables, f, indent=2)
        print("Step2: Finsihing postprocessing the tables")

    if '3' in steps:
        dictionary = {}
        # Step3: Getting the hyperlinks
        rs = pool.map(crawl_hyperlinks, zip(tables, range(len(tables))))
        title_dictionary = dict(rs)
        dictionary.update(title_dictionary)
        print("Step3: Finsihing downloading hyperlinks")
        rs = pool.map(summarize, tables)
        title_dictionary = dict(rs)
        dictionary.update(title_dictionary)
        print('totally {}'.format(len(dictionary)))
        failed = [k for k, v in dictionary.items() if v == 'N/A']
        print('failed {} items'.format(len(failed)))
        for k, v in dictionary.items():
            dictionary[k] = re.sub(r'\[[\d]+\]', '', v).strip()
        merged_unquote = {}
        for k, v in dictionary.items():
            merged_unquote[urllib.parse.unquote(k)] = v
        with open('{}/merged_unquote.json'.format(output_folder), 'w') as f:
            json.dump(merged_unquote, f, indent=2)
        print("Step3: Finishing collecting the hyperlinks")

    if '4' in steps:
        # Step5: distribute the tables into separate files
        with open('{}/processed_new_table_postfiltering.json'.format(output_folder), 'r') as f:
            tables = json.load(f)
        for idx, table in enumerate(tables):
            table['idx'] = idx
            for row_idx, row in enumerate(table['data']):
                for col_idx, cell in enumerate(row):
                    for i, ent in enumerate(cell[0]):
                        if ent:
                            table['data'][row_idx][col_idx][0][i] = clean_cell_text(ent)
            
            for col_idx, header in enumerate(table['header']):
                for i, ent in enumerate(header[0]):
                    if ent:
                        table['header'][col_idx][0][i] = clean_cell_text(ent)
            
            with open('{}/tables/{}.json'.format(output_folder, table['idx']), 'w') as f:
                json.dump(table, f, indent=2)
        print("Step4: Finishing distributing the tables")

    if '5' in steps:
        # Step 6: distribute the request into separate files 
        with open('{}/merged_unquote.json'.format(output_folder), 'r') as f:
            merged_unquote = json.load(f)
        for k in merged_unquote:
            merged_unquote[k] = clean_text(k, merged_unquote[k])
        
        def get_request_summary(f_id):
            if f_id.endswith('.json'):
                with open('{}/tables/{}'.format(output_folder, f_id)) as f:
                    table = json.load(f)
            
                local_dict = {}
                for d in table['header']:
                    for url in d[1]:
                        if url:
                            url = urllib.parse.unquote(url)
                            local_dict[url] = merged_unquote[url]
                
                for row in table['data']:
                    for cell in row:
                        for url in cell[1]:
                            if url:
                                url = urllib.parse.unquote(url)
                                local_dict[url] = merged_unquote[url]

                with open('{}/request/{}'.format(output_folder, f_id), 'w') as f:
                    json.dump(local_dict, f, indent=2)
        
        for f in os.listdir('{}/tables/'.format(output_folder)):
            get_request_summary(f)
        print("Step5: Finishing distributing the requests")

    if '6' in steps:
        # Step7: tokenize the tables and request
        if not os.path.exists('{}/request_tok'.format(output_folder)):
            os.mkdir('{}/request_tok'.format(output_folder))
        if not os.path.exists('{}/tables_tok'.format(output_folder)):
            os.mkdir('{}/tables_tok'.format(output_folder))
        pool.map(tokenization_req, os.listdir('{}/request'.format(output_folder)))
        pool.map(tokenization_tab, os.listdir('{}/tables'.format(output_folder)))

        pool.close()
        pool.join()
        print("Step6: Finishing tokenization")
