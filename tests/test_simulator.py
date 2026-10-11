import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'simulator'))
from app.main import Graph, GraphError, build_graph_info, dsu_netlist, validate_formula


def n(i,t,**data): return {'id':i,'type':t,'data':data}

def e(s,sh,t,th): return {'id':f'{s}-{t}-{th}','source':s,'sourceHandle':sh,'target':t,'targetHandle':th}


def test_acceptance_graph_1_netlist():
    g=Graph(nodes=[n('n2','number',value='2'),n('n3','number',value='3'),n('add','add'),n('d','display')],edges=[e('n2','out','add','a'),e('n3','out','add','b'),e('add','out','d','x')])
    nodes,inc,out=build_graph_info(g); lines,_,_=dsu_netlist(g,nodes,inc)
    assert any('DC 2.0' in x for x in lines)
    assert any('V(' in x and '+' in x for x in lines)

def test_acceptance_graph_3_fanout_is_allowed():
    g=Graph(nodes=[n('n','number',value='7'),n('m','multiply'),n('d','display')],edges=[e('n','out','m','a'),e('n','out','m','b'),e('m','out','d','x')])
    build_graph_info(g)

def test_loop_detection():
    g=Graph(nodes=[n('a','add'),n('m','multiply')],edges=[e('a','out','m','a'),e('m','out','a','a')])
    try: build_graph_info(g)
    except GraphError as ex: assert any('cycle' in x['message'].lower() for x in ex.errors)
    else: raise AssertionError('cycle not detected')

def test_unsafe_formula():
    bad='a + b\n.control\nshell ls'
    try: validate_formula(bad)
    except ValueError as ex: assert 'Formula' in str(ex) or 'Unsafe' in str(ex)
    else: raise AssertionError('unsafe formula accepted')


def test_react_flow_custom_node_type():
    g = Graph(nodes=[{'id': 'one', 'type': 'custom', 'data': {'type': 'number', 'value': '2'}}], edges=[])
    nodes, _, _ = build_graph_info(g)
    assert nodes['one']['data']['type'] == 'number'


def test_ngspice_voltage_names_case_insensitive():
    from app.main import parse_values
    parsed = parse_values('Node Voltage\nN1  2.000000e+00\nn2  -3.500000e+00\n')
    assert parsed['n1'] == 2.0
    assert parsed['n2'] == -3.5


def test_simulation_add_and_display(monkeypatch):
    from app.main import simulate
    from types import SimpleNamespace
    from pathlib import Path
    def fake_run(command, **kwargs):
        netlist = Path(command[-1]).read_text()
        assert 'DC 2.0' in netlist and 'DC 3.0' in netlist
        assert ' + ' in netlist
        Path(command[command.index('-o')+1]).write_text('n1 2.0\nn2 3.0\nn3 5.0\n')
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr('app.main.subprocess.run', fake_run)
    g=Graph(nodes=[n('n2','number',value='2'),n('n3','number',value='3'),n('add','add'),n('d','display')],edges=[e('n2','out','add','a'),e('n3','out','add','b'),e('add','out','d','x')])
    result=simulate(g)
    assert result['status']=='ok'
    assert result['nodeValues']['add']==5.0
    assert result['nodeValues']['d']==5.0
