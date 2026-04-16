# -*- coding: utf-8 -*-
from core.utils import parse_json, parse_sql_from_string, add_prefix, load_json_file, extract_world_info, is_email, is_valid_date_column
from core.llm import safe_call_llm
from core.state import SQLaxyState
from func_timeout import func_set_timeout, FunctionTimedOut

from core.const import (
    selector_template,
    decompose_template_bird,
    decompose_template_spider,
    refiner_template,
)
from typing import List
from copy import deepcopy

import sqlite3
import time
import sys
import os
import glob
import pandas as pd
from tqdm import tqdm, trange
from pprint import pprint
import pdb
import tiktoken


class Selector:
    """
    Get database description and if need, extract relative tables & columns
    """

    def __init__(self, data_path: str, tables_json_path: str, model_name: str, dataset_name:str, lazy: bool = False, without_selector: bool = False, skill_manager=None):
        self.data_path = data_path.strip('/').strip('\\')
        self.tables_json_path = tables_json_path
        self.model_name = model_name
        self.dataset_name = dataset_name
        self.db2infos = {}  # summary of db (stay in the memory during generating prompt)
        self.db2dbjsons = {} # store all db to tables.json dict by tables_json_path
        self.init_db2jsons()
        if not lazy:
            self._load_all_db_info()
        self.without_selector = without_selector
        self.skill_manager = skill_manager
    
    def init_db2jsons(self):
        if not os.path.exists(self.tables_json_path):
            raise FileNotFoundError(f"tables.json not found in {self.tables_json_path}")
        data = load_json_file(self.tables_json_path)
        for item in data:
            db_id = item['db_id']
            
            table_names = item['table_names']
            # 统计表格数量
            item['table_count'] = len(table_names)
            
            column_count_lst = [0] * len(table_names)
            for tb_idx, col in item['column_names']:
                if tb_idx >= 0:
                    column_count_lst[tb_idx] += 1
            # 最大列名数量
            item['max_column_count'] = max(column_count_lst)
            item['total_column_count'] = sum(column_count_lst)
            item['avg_column_count'] = sum(column_count_lst) // len(table_names)
            
            # print()
            # print(f"db_id: {db_id}")
            # print(f"table_count: {item['table_count']}")
            # print(f"max_column_count: {item['max_column_count']}")
            # print(f"total_column_count: {item['total_column_count']}")
            # print(f"avg_column_count: {item['avg_column_count']}")
            # time.sleep(0.2)
            self.db2dbjsons[db_id] = item
    
    
    def _get_column_attributes(self, cursor, table):
        # # 查询表格的列属性信息
        cursor.execute(f"PRAGMA table_info(`{table}`)")
        columns = cursor.fetchall()

        # 构建列属性信息的字典列表
        columns_info = []
        primary_keys = []
        column_names = []
        column_types = []
        for column in columns:
            column_names.append(column[1])
            column_types.append(column[2])
            is_pk = bool(column[5])
            if is_pk:
                primary_keys.append(column[1])
            column_info = {
                'name': column[1],  # 列名
                'type': column[2],  # 数据类型
                'not_null': bool(column[3]),  # 是否允许为空
                'primary_key': bool(column[5])  # 是否为主键
            }
            columns_info.append(column_info)
        """
        table: satscores
        [{'name': 'cds', 'not_null': True, 'primary_key': True, 'type': 'TEXT'},
        {'name': 'rtype', 'not_null': True, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'sname', 'not_null': False, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'dname', 'not_null': False, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'cname', 'not_null': False, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'enroll12','not_null': True, 'primary_key': False, 'type': 'INTEGER'},
        ...
        """
        return column_names, column_types

    
    def _get_unique_column_values_str(self, cursor, table, column_names, column_types, 
                                      json_column_names, is_key_column_lst):

        col_to_values_str_lst = []
        col_to_values_str_dict = {}

        key_col_list = [json_column_names[i] for i, flag in enumerate(is_key_column_lst) if flag]

        len_column_names = len(column_names)

        for idx, column_name in enumerate(column_names):
            # 查询每列的 distinct value, 从指定的表中选择指定列的值，并按照该列的值进行分组。然后按照每个分组中的记录数量进行降序排序。
            # print(f"In _get_unique_column_values_str, processing column: {idx}/{len_column_names} col_name: {column_name} of table: {table}", flush=True)

            # skip pk and fk
            if column_name in key_col_list:
                continue
            
            lower_column_name: str = column_name.lower()
            # if lower_column_name ends with [id, email, url], just use empty str
            if lower_column_name.endswith('id') or \
                lower_column_name.endswith('email') or \
                lower_column_name.endswith('url'):
                values_str = ''
                col_to_values_str_dict[column_name] = values_str
                continue

            sql = f"SELECT `{column_name}` FROM `{table}` GROUP BY `{column_name}` ORDER BY COUNT(*) DESC"
            cursor.execute(sql)
            values = cursor.fetchall()
            values = [value[0] for value in values]

            values_str = ''
            # try to get value examples str, if exception, just use empty str
            try:
                values_str = self._get_value_examples_str(values, column_types[idx])
            except Exception as e:
                print(f"\nerror: get_value_examples_str failed, Exception:\n{e}\n")

            col_to_values_str_dict[column_name] = values_str


        for k, column_name in enumerate(json_column_names):
            values_str = ''
            # print(f"column_name: {column_name}")
            # print(f"col_to_values_str_dict: {col_to_values_str_dict}")

            is_key = is_key_column_lst[k]

            # pk or fk do not need value str
            if is_key:
                values_str = ''
            elif column_name in col_to_values_str_dict:
                values_str = col_to_values_str_dict[column_name]
            else:
                print(col_to_values_str_dict)
                time.sleep(3)
                print(f"error: column_name: {column_name} not found in col_to_values_str_dict")
            
            col_to_values_str_lst.append([column_name, values_str])
        
        return col_to_values_str_lst
    

    # 这个地方需要精细化处理
    def _get_value_examples_str(self, values: List[object], col_type: str):
        if not values:
            return ''
        if len(values) > 10 and col_type in ['INTEGER', 'REAL', 'NUMERIC', 'FLOAT', 'INT']:
            return ''
        
        vals = []
        has_null = False
        for v in values:
            if v is None:
                has_null = True
            else:
                tmp_v = str(v).strip()
                if tmp_v == '':
                    continue
                else:
                    vals.append(v)
        if not vals:
            return ''
        
        # drop meaningless values
        if col_type in ['TEXT', 'VARCHAR']:
            new_values = []
            
            for v in vals:
                if not isinstance(v, str):
                    
                    new_values.append(v)
                else:
                    if self.dataset_name == 'spider':
                        v = v.strip()
                    if v == '': # exclude empty string
                        continue
                    elif ('https://' in v) or ('http://' in v): # exclude url
                        return ''
                    elif is_email(v): # exclude email
                        return ''
                    else:
                        new_values.append(v)
            vals = new_values
            tmp_vals = [len(str(a)) for a in vals]
            if not tmp_vals:
                return ''
            max_len = max(tmp_vals)
            if max_len > 50:
                return ''
        
        if not vals:
            return ''
        
        vals = vals[:6]

        is_date_column = is_valid_date_column(vals)
        if is_date_column:
            vals = vals[:1]

        if has_null:
            vals.insert(0, None)
        
        val_str = str(vals)
        return val_str
    
    def _load_single_db_info(self, db_id: str) -> dict:
        table2coldescription = {} # Dict {table_name: [(column_name, full_column_name, column_description), ...]}
        table2primary_keys = {} # DIct {table_name: [primary_key_column_name,...]}
        
        table_foreign_keys = {} # Dict {table_name: [(from_col, to_table, to_col), ...]}
        table_unique_column_values = {} # Dict {table_name: [(column_name, examples_values_str)]}

        db_dict = self.db2dbjsons[db_id]

        # todo: gather all pk and fk id list
        important_key_id_lst = []
        keys = db_dict['primary_keys'] + db_dict['foreign_keys']
        for col_id in keys:
            if isinstance(col_id, list):
                important_key_id_lst.extend(col_id)
            else:
                important_key_id_lst.append(col_id)


        db_path = f"{self.data_path}/{db_id}/{db_id}.sqlite"
        conn = sqlite3.connect(db_path)
        conn.text_factory = lambda b: b.decode(errors="ignore")  # avoid gbk/utf8 error, copied from sql-eval.exec_eval
        cursor = conn.cursor()

        table_names_original_lst = db_dict['table_names_original']
        for tb_idx, tb_name in enumerate(table_names_original_lst):
            # 遍历原始列名
            all_column_names_original_lst = db_dict['column_names_original']
            
            all_column_names_full_lst = db_dict['column_names']
            col2dec_lst = []

            pure_column_names_original_lst = []
            is_key_column_lst = []
            for col_idx, (root_tb_idx, orig_col_name) in enumerate(all_column_names_original_lst):
                if root_tb_idx != tb_idx:
                    continue
                pure_column_names_original_lst.append(orig_col_name)
                if col_idx in important_key_id_lst:
                    is_key_column_lst.append(True)
                else:
                    is_key_column_lst.append(False)
                full_col_name: str = all_column_names_full_lst[col_idx][1]
                full_col_name = full_col_name.replace('_', ' ')
                cur_desc_obj = [orig_col_name, full_col_name, '']
                col2dec_lst.append(cur_desc_obj)
            table2coldescription[tb_name] = col2dec_lst
            
            table_foreign_keys[tb_name] = []
            table_unique_column_values[tb_name] = []
            table2primary_keys[tb_name] = []

            # column_names, column_types
            all_sqlite_column_names_lst, all_sqlite_column_types_lst = self._get_column_attributes(cursor, tb_name)
            col_to_values_str_lst = self._get_unique_column_values_str(cursor, tb_name, all_sqlite_column_names_lst, all_sqlite_column_types_lst, pure_column_names_original_lst, is_key_column_lst)
            table_unique_column_values[tb_name] = col_to_values_str_lst
        
        # table_foreign_keys 处理起来麻烦一些
        foreign_keys_lst = db_dict['foreign_keys']

        for from_col_idx, to_col_idx in foreign_keys_lst:
            from_col_name = all_column_names_original_lst[from_col_idx][1]
            from_tb_idx = all_column_names_original_lst[from_col_idx][0]
            from_tb_name = table_names_original_lst[from_tb_idx]

            to_col_name = all_column_names_original_lst[to_col_idx][1]
            to_tb_idx = all_column_names_original_lst[to_col_idx][0]
            to_tb_name = table_names_original_lst[to_tb_idx]

            table_foreign_keys[from_tb_name].append((from_col_name, to_tb_name, to_col_name))
        

        # table2primary_keys
        for pk_idx in db_dict['primary_keys']:
            # if pk_idx is int
            pk_idx_lst = []
            if isinstance(pk_idx, int):
                pk_idx_lst.append(pk_idx)
            elif isinstance(pk_idx, list):
                pk_idx_lst = pk_idx
            else:
                err_message = f"pk_idx: {pk_idx} is not int or list"
                print(err_message)
                raise Exception(err_message)
            for cur_pk_idx in pk_idx_lst:
                tb_idx = all_column_names_original_lst[cur_pk_idx][0]
                col_name = all_column_names_original_lst[cur_pk_idx][1]
                tb_name = table_names_original_lst[tb_idx]
                table2primary_keys[tb_name].append(col_name)
        
        cursor.close()
        # print table_name and primary keys
        # for tb_name, pk_keys in table2primary_keys.items():
        #     print(f"table_name: {tb_name}; primary key: {pk_keys}")
        time.sleep(3)

        # wrap result and return
        result = {
            "desc_dict": table2coldescription,
            "value_dict": table_unique_column_values,
            "pk_dict": table2primary_keys,
            "fk_dict": table_foreign_keys
        }
        return result

    def _load_all_db_info(self):
        print("\nLoading all database info...", file=sys.stdout, flush=True)
        db_ids = [item for item in os.listdir(self.data_path)]
        for i in trange(len(db_ids)):
            db_id = db_ids[i]
            db_info = self._load_single_db_info(db_id)
            self.db2infos[db_id] = db_info
    
    
    def _build_bird_table_schema_sqlite_str(self, table_name, new_columns_desc, new_columns_val):
        schema_desc_str = ''
        schema_desc_str += f"CREATE TABLE {table_name}\n"
        extracted_column_infos = []
        for (col_name, full_col_name, col_extra_desc), (_, col_values_str) in zip(new_columns_desc, new_columns_val):
            # district_id INTEGER PRIMARY KEY, -- location of branch
            col_line_text = ''
            col_extra_desc = 'And ' + str(col_extra_desc) if col_extra_desc != '' and str(col_extra_desc) != 'nan' else ''
            col_extra_desc = col_extra_desc[:100]
            col_line_text = ''
            col_line_text += f"  {col_name},  --"
            if full_col_name != '':
                full_col_name = full_col_name.strip()
                col_line_text += f" {full_col_name},"
            if col_values_str != '':
                col_line_text += f" Value examples: {col_values_str}."
            if col_extra_desc != '':
                col_line_text += f" {col_extra_desc}"
            extracted_column_infos.append(col_line_text)
        schema_desc_str += '{\n' + '\n'.join(extracted_column_infos) + '\n}' + '\n'
        return schema_desc_str
    
    def _build_bird_table_schema_list_str(self, table_name, new_columns_desc, new_columns_val):
        schema_desc_str = ''
        schema_desc_str += f"# Table: {table_name}\n"
        extracted_column_infos = []
        for (col_name, full_col_name, col_extra_desc), (_, col_values_str) in zip(new_columns_desc, new_columns_val):
            col_extra_desc = 'And ' + str(col_extra_desc) if col_extra_desc != '' and str(col_extra_desc) != 'nan' else ''
            col_extra_desc = col_extra_desc[:100]

            col_line_text = ''
            col_line_text += f'  ('
            col_line_text += f"{col_name},"

            if full_col_name != '':
                full_col_name = full_col_name.strip()
                col_line_text += f" {full_col_name}."
            if col_values_str != '':
                col_line_text += f" Value examples: {col_values_str}."
            if col_extra_desc != '':
                col_line_text += f" {col_extra_desc}"
            col_line_text += '),'
            extracted_column_infos.append(col_line_text)
        schema_desc_str += '[\n' + '\n'.join(extracted_column_infos).strip(',') + '\n]' + '\n'
        return schema_desc_str
    
    def _get_db_desc_str(self,
                         db_id: str,
                         extracted_schema: dict,
                         use_gold_schema: bool = False) -> List[str]:
        """
        Add foreign keys, and value descriptions of focused columns.
        :param db_id: name of sqlite database
        :param extracted_schema: {table_name: "keep_all" or "drop_all" or ['col_a', 'col_b']}
        :return: Detailed columns info of db; foreign keys info of db
        """
        if self.db2infos.get(db_id, {}) == {}:  # lazy load
            self.db2infos[db_id] = self._load_single_db_info(db_id)
        db_info = self.db2infos[db_id]
        desc_info = db_info['desc_dict']  # table:str -> columns[(column_name, full_column_name, extra_column_desc): str]
        value_info = db_info['value_dict']  # table:str -> columns[(column_name, value_examples_str): str]
        pk_info = db_info['pk_dict']  # table:str -> primary keys[column_name: str]
        fk_info = db_info['fk_dict']  # table:str -> foreign keys[(column_name, to_table, to_column): str]
        tables_1, tables_2, tables_3 = desc_info.keys(), value_info.keys(), fk_info.keys()
        assert set(tables_1) == set(tables_2)
        assert set(tables_2) == set(tables_3)

        # print(f"desc_info: {desc_info}\n\n")

        # schema_desc_str = f"[db_id]: {db_id}\n"
        schema_desc_str = ''  # for concat
        db_fk_infos = []  # use list type for unique check in db

        # print(f"extracted_schema:\n")
        # pprint(extracted_schema)
        # print()

        print(f"db_id: {db_id}")
        # For selector recall and compression rate calculation
        chosen_db_schem_dict = {} # {table_name: ['col_a', 'col_b'], ..}
        for (table_name, columns_desc), (_, columns_val), (_, fk_info), (_, pk_info) in \
                zip(desc_info.items(), value_info.items(), fk_info.items(), pk_info.items()):
            
            table_decision = extracted_schema.get(table_name, '')
            if table_decision == '' and use_gold_schema:
                continue

            # columns_desc = [(column_name, full_column_name, extra_column_desc): str]
            # columns_val = [(column_name, value_examples_str): str]
            # fk_info = [(column_name, to_table, to_column): str]
            # pk_info = [column_name: str]

            all_columns = [name for name, _, _ in columns_desc]
            primary_key_columns = [name for name in pk_info]
            foreign_key_columns = [name for name, _, _ in fk_info]

            important_keys = primary_key_columns + foreign_key_columns

            new_columns_desc = []
            new_columns_val = []

            print(f"table_name: {table_name}")
            if table_decision == "drop_all":
                new_columns_desc = deepcopy(columns_desc[:6])
                new_columns_val = deepcopy(columns_val[:6])
            elif table_decision == "keep_all" or table_decision == '':
                new_columns_desc = deepcopy(columns_desc)
                new_columns_val = deepcopy(columns_val)
            else:
                llm_chosen_columns = table_decision
                print(f"llm_chosen_columns: {llm_chosen_columns}")
                append_col_names = []
                for idx, col in enumerate(all_columns):
                    if col in important_keys:
                        new_columns_desc.append(columns_desc[idx])
                        new_columns_val.append(columns_val[idx])
                        append_col_names.append(col)
                    elif col in llm_chosen_columns:
                        new_columns_desc.append(columns_desc[idx])
                        new_columns_val.append(columns_val[idx])
                        append_col_names.append(col)
                    else:
                        pass
                
                # todo: check if len(new_columns_val) ≈ 6
                if len(all_columns) > 6 and len(new_columns_val) < 6:
                    for idx, col in enumerate(all_columns):
                        if len(append_col_names) >= 6:
                            break
                        if col not in append_col_names:
                            new_columns_desc.append(columns_desc[idx])
                            new_columns_val.append(columns_val[idx])
                            append_col_names.append(col)

            # 统计经过 Selector 筛选后的表格信息
            chosen_db_schem_dict[table_name] = [col_name for col_name, _, _ in new_columns_desc]
            
            # 1. Build schema part of prompt
            # schema_desc_str += self._build_bird_table_schema_sqlite_str(table_name, new_columns_desc, new_columns_val)
            schema_desc_str += self._build_bird_table_schema_list_str(table_name, new_columns_desc, new_columns_val)

            # 2. Build foreign key part of prompt
            for col_name, to_table, to_col in fk_info:
                from_table = table_name
                if '`' not in str(col_name):
                    col_name = f"`{col_name}`"
                if '`' not in str(to_col):
                    to_col = f"`{to_col}`"
                fk_link_str = f"{from_table}.{col_name} = {to_table}.{to_col}"
                if fk_link_str not in db_fk_infos:
                    db_fk_infos.append(fk_link_str)
        fk_desc_str = '\n'.join(db_fk_infos)
        schema_desc_str = schema_desc_str.strip()
        fk_desc_str = fk_desc_str.strip()
        
        return schema_desc_str, fk_desc_str, chosen_db_schem_dict

    def _is_need_prune(self, db_id: str, db_schema: str):
        # encoder = tiktoken.get_encoding("cl100k_base")
        # tokens = encoder.encode(db_schema)
        # return len(tokens) >= 25000
        db_dict = self.db2dbjsons[db_id]
        avg_column_count = db_dict['avg_column_count']
        total_column_count = db_dict['total_column_count']
        if avg_column_count <= 6 and total_column_count <= 30:
            return False
        else:
            return True

    def _prune(self,
               state: SQLaxyState,
               db_id: str,
               query: str,
               db_schema: str,
               db_fk: str,
               evidence: str = None,
               ) -> tuple:
        """Returns (extracted_schema_dict, skill_context)."""
        template = selector_template
        skill_context = {}

        if self.skill_manager:
            from evosql.config import USE_PROGRESSIVE_INJECTION
            if USE_PROGRESSIVE_INJECTION:
                from evosql.prompt_injector import inject_skills_progressive
                template, skill_context = inject_skills_progressive(
                    template, self.skill_manager, "selector",
                    question=query, schema_text=db_schema,
                )
            else:
                from evosql.prompt_injector import inject_skills_into_prompt
                template = inject_skills_into_prompt(
                    template, self.skill_manager, "selector",
                    question=query, schema_text=db_schema,
                )

        prompt = template.format(db_id=db_id, query=query, evidence=evidence, desc_str=db_schema, fk_str=db_fk)
        word_info = extract_world_info(state)
        reply = safe_call_llm(prompt, **word_info)
        extracted_schema_dict = parse_json(reply)
        return extracted_schema_dict, skill_context

    def process(self, state: SQLaxyState) -> dict:
        """
        :return: dict with desc_str, fk_str, chosen_db_schem_dict, pruned, extracted_schema
        """
        db_id = state.get("db_id")
        ext_sch = state.get("extracted_schema") or {}
        query = state.get("query")
        evidence = state.get("evidence")
        use_gold_schema = bool(ext_sch)
        db_schema, db_fk, chosen_db_schem_dict = self._get_db_desc_str(
            db_id=db_id, extracted_schema=ext_sch, use_gold_schema=use_gold_schema
        )
        need_prune = self._is_need_prune(db_id, db_schema)
        if self.without_selector:
            need_prune = False
        if ext_sch == {} and need_prune:
            skill_context = {}
            try:
                raw_extracted_schema_dict, skill_context = self._prune(
                    state, db_id=db_id, query=query, db_schema=db_schema, db_fk=db_fk, evidence=evidence
                )
            except Exception as e:
                print(e)
                raw_extracted_schema_dict = {}

            print(f"query: {state['query']}\n")
            db_schema_str, db_fk, chosen_db_schem_dict = self._get_db_desc_str(
                db_id=db_id, extracted_schema=raw_extracted_schema_dict
            )

            result = {
                "extracted_schema": raw_extracted_schema_dict,
                "chosen_db_schem_dict": chosen_db_schem_dict,
                "desc_str": db_schema_str,
                "fk_str": db_fk,
                "pruned": True,
            }
            if skill_context:
                result["skill_context"] = skill_context
            return result
        return {
            "chosen_db_schem_dict": chosen_db_schem_dict,
            "desc_str": db_schema,
            "fk_str": db_fk,
            "pruned": False,
        }


def decomposer_process(state: SQLaxyState, dataset_name: str, skill_manager=None) -> dict:
    query = state.get("query")
    evidence = state.get("evidence")
    schema_info = state.get("desc_str")
    fk_info = state.get("fk_str")

    decomposer_context = {}

    if dataset_name == "bird":
        template = decompose_template_bird
        if skill_manager:
            from evosql.config import USE_PROGRESSIVE_INJECTION
            if USE_PROGRESSIVE_INJECTION:
                from evosql.prompt_injector import inject_skills_progressive
                selector_context = state.get("skill_context", {})
                template, decomposer_context = inject_skills_progressive(
                    template, skill_manager, "decomposer",
                    question=query, schema_text=f"{query} {evidence} {schema_info}",
                    context_from_prev_stage=selector_context,
                )
            else:
                from evosql.prompt_injector import inject_skills_into_prompt
                template = inject_skills_into_prompt(
                    template, skill_manager, "decomposer",
                    question=query, schema_text=f"{query} {evidence} {schema_info}",
                )
        prompt = template.format(
            query=query, desc_str=schema_info, fk_str=fk_info, evidence=evidence
        )
    else:
        template = decompose_template_spider
        if skill_manager:
            from evosql.config import USE_PROGRESSIVE_INJECTION
            if USE_PROGRESSIVE_INJECTION:
                from evosql.prompt_injector import inject_skills_progressive
                selector_context = state.get("skill_context", {})
                template, decomposer_context = inject_skills_progressive(
                    template, skill_manager, "decomposer",
                    question=query, schema_text=f"{query} {schema_info}",
                    context_from_prev_stage=selector_context,
                )
            else:
                from evosql.prompt_injector import inject_skills_into_prompt
                template = inject_skills_into_prompt(
                    template, skill_manager, "decomposer",
                    question=query, schema_text=f"{query} {schema_info}",
                )
        prompt = template.format(
            query=query, desc_str=schema_info, fk_str=fk_info
        )

    word_info = extract_world_info(state)
    reply = safe_call_llm(prompt, **word_info).strip()

    res = ""
    qa_pairs = reply

    try:
        res = parse_sql_from_string(reply)
    except Exception as e:
        res = f"error: {str(e)}"
        print(res)
        time.sleep(1)

    result = {"final_sql": res, "qa_pairs": qa_pairs, "fixed": False}
    if decomposer_context:
        result["skill_context"] = decomposer_context
    return result


class _RefinerCore:
    def __init__(self, data_path: str, dataset_name: str):
        self.data_path = data_path
        self.dataset_name = dataset_name

    @func_set_timeout(120)
    def _execute_sql(self, sql: str, db_id: str) -> dict:
        # Get database connection
        db_path = f"{self.data_path}/{db_id}/{db_id}.sqlite"
        conn = sqlite3.connect(db_path)
        conn.text_factory = lambda b: b.decode(errors="ignore")
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            result = cursor.fetchall()
            return {
                "sql": str(sql),
                "data": result[:5],
                "sqlite_error": "",
                "exception_class": ""
            }
        except sqlite3.Error as er:
            return {
                "sql": str(sql),
                "sqlite_error": str(' '.join(er.args)),
                "exception_class": str(er.__class__)
            }
        except Exception as e:
            return {
                "sql": str(sql),
                "sqlite_error": str(e.args),
                "exception_class": str(type(e).__name__)
            }

    def _is_need_refine(self, exec_result: dict):
        # spider exist dirty values, even gold sql execution result is None
        if self.dataset_name == 'spider':
            if 'data' not in exec_result:
                return True
            return False
        
        data = exec_result.get('data', None)
        if data is not None:
            if len(data) == 0:
                exec_result['sqlite_error'] = 'no data selected'
                return True
            for t in data:
                for n in t:
                     if n is None:  # fixme fixme fixme fixme fixme
                        exec_result['sqlite_error'] = 'exist None value, you can add `NOT NULL` in SQL'
                        return True
            return False
        else:
            return True

    def _refine(
        self,
        state: SQLaxyState,
        query: str,
        evidence: str,
        schema_info: str,
        fk_info: str,
        error_info: dict,
        skill_manager=None,
    ) -> str:
        sql_arg = add_prefix(error_info.get("sql"))
        sqlite_error = error_info.get("sqlite_error")
        exception_class = error_info.get("exception_class")

        template = refiner_template
        if skill_manager:
            from evosql.config import USE_PROGRESSIVE_INJECTION
            if USE_PROGRESSIVE_INJECTION:
                from evosql.prompt_injector import inject_skills_progressive
                prev_context = state.get("skill_context", {})
                template, _ = inject_skills_progressive(
                    template, skill_manager, "refiner",
                    question=query, schema_text=schema_info,
                    error_text=f"{sqlite_error} {exception_class}",
                    context_from_prev_stage=prev_context,
                )
            else:
                from evosql.prompt_injector import inject_skills_into_prompt
                template = inject_skills_into_prompt(
                    template, skill_manager, "refiner",
                    question=query, schema_text=schema_info,
                    error_text=f"{sqlite_error} {exception_class}",
                )

        prompt = template.format(
            query=query,
            evidence=evidence,
            desc_str=schema_info,
            fk_str=fk_info,
            sql=sql_arg,
            sqlite_error=sqlite_error,
            exception_class=exception_class,
        )

        word_info = extract_world_info(state)
        reply = safe_call_llm(prompt, **word_info)
        res = parse_sql_from_string(reply)
        return res


def _semantic_sanity_check(data: list, query: str) -> str:
    """Heuristic check for suspicious results that might indicate semantic errors."""
    query_lower = query.lower()
    if not data:
        return ""
    row_count = len(data)
    has_count_query = any(w in query_lower for w in ["how many", "count", "number of", "total"])
    if has_count_query and row_count == 1 and len(data[0]) == 1:
        val = data[0][0]
        if val == 0:
            return "COUNT result is 0 — verify this is correct given the question"
    if row_count > 100 and not any(w in query_lower for w in ["all", "list", "every"]):
        return f"Query returned {row_count} rows — verify the result is not too broad"
    return ""


def refiner_process(state: SQLaxyState, data_path: str, dataset_name: str, skill_manager=None) -> dict:
    core = _RefinerCore(data_path, dataset_name)
    db_id = state.get("db_id")
    old_sql = state.get("pred") or state.get("final_sql", "")
    query = state.get("query")
    evidence = state.get("evidence")
    schema_info = state.get("desc_str")
    fk_info = state.get("fk_str")
    try_times = state.get("try_times", 0)
    cur_fixed = state.get("fixed", False)

    if "error" in old_sql:
        return {
            "try_times": try_times + 1,
            "pred": old_sql,
            "fixed": cur_fixed,
            "need_refine": False,
        }

    error_info = None
    is_timeout = False
    try:
        error_info = core._execute_sql(old_sql, db_id)
    except FunctionTimedOut:
        is_timeout = True
    except Exception:
        is_timeout = True

    if is_timeout:
        return {
            "try_times": try_times + 1,
            "pred": old_sql,
            "fixed": cur_fixed,
            "need_refine": False,
        }

    is_need = core._is_need_refine(error_info)

    if not is_need and try_times == 0:
        data = error_info.get("data", [])
        hint = _semantic_sanity_check(data, query)
        if hint:
            print(f"  [SemanticCheck] {hint}")
            error_info["sqlite_error"] = hint
            error_info["exception_class"] = "SemanticWarning"
            is_need = True

    if not is_need:
        return {
            "try_times": try_times + 1,
            "pred": old_sql,
            "fixed": cur_fixed,
            "need_refine": False,
        }

    new_sql = core._refine(state, query, evidence, schema_info, fk_info, error_info, skill_manager=skill_manager)
    return {
        "try_times": try_times + 1,
        "pred": new_sql,
        "fixed": True,
        "need_refine": True,
    }


if __name__ == "__main__":
    m = 0