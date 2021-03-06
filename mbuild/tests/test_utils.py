import difflib

import numpy as np
import pytest

from mbuild.tests.base_test import BaseTest
from mbuild.utils.io import get_fn, import_
from mbuild.utils.validation import assert_port_exists
from mbuild.utils.jsutils import overwrite_nglview_default


class TestUtils(BaseTest):

    def test_assert_port_exists(self, ch2):
        assert_port_exists('up', ch2)
        with pytest.raises(ValueError):
            assert_port_exists('dog', ch2)

    def test_structure_reproducibility(self, alkane_monolayer):
        filename = 'monolayer-tmp.pdb'
        alkane_monolayer.save(filename)
        with open(get_fn('monolayer.pdb')) as file1:
            with open('monolayer-tmp.pdb') as file2:
                diff = difflib.ndiff(file1.readlines(), file2.readlines())
        changes = [l for l in diff if l.startswith('+ ') or l.startswith('- ')]
        assert not changes

    def test_fn(self):
        get_fn('benzene.mol2')

        with pytest.raises((IOError, OSError)):
            get_fn('garbage_file_name.foo')

    def test_import(self):
        assert np == import_('numpy')

        with pytest.raises(ImportError):
            import_('garbagepackagename')

    def test_js_utils(self):
        nglview = import_('nglview')
        with pytest.raises(TypeError):
            overwrite_nglview_default(object())
        test_widget = nglview.NGLWidget()
        overwrite_nglview_default(test_widget)
        assert hasattr(test_widget, 'stage')
        assert isinstance(test_widget._ngl_msg_archive, list)
        assert len(test_widget._ngl_msg_archive) == 2
        assert isinstance(test_widget._ngl_msg_archive[0], dict)
        message_dict = test_widget._ngl_msg_archive[0]
        assert message_dict['target'] == 'Widget'
        assert message_dict['type'] == 'call_method'
        assert message_dict['methodName'] == 'executeCode'
        assert message_dict['args'] == [
                    """
                    this.stage.mouseControls.add('hoverPick', (stage, pickingProxy) => {
                        let tooltip = this.stage.tooltip;
                        if(pickingProxy && pickingProxy.atom && !pickingProxy.bond){
                            let atom = pickingProxy.atom;
                            tooltip.innerText = "ATOM: " + atom.qualifiedName() + ", Index: " + atom.index;
                        }
                    });
                 """
                ]
        message_dict = test_widget._ngl_msg_archive[1]
        assert message_dict['target'] == 'Widget'
        assert message_dict['type'] == 'call_method'
        assert message_dict['methodName'] == 'executeCode'
        assert message_dict['args'] == [
            """
                    this.stage.signals.clicked.removeAll();
                    this.stage.signals.clicked.add((pickingProxy) => {
                            if(pickingProxy){
                               let pickingText = null;
                               this.model.set('picked', {});
                               this.touch();
                               let currentPick = {};
                               if(pickingProxy.atom){
                                    currentPick.atom1 = pickingProxy.atom.toObject();
                                    currentPick.atom1.name = pickingProxy.atom.qualifiedName();
                                    pickingText = "Atom: " + currentPick.atom1.name + ", Index: " 
                                                  + pickingProxy.atom.index;
                               }
                               else if(pickingProxy.bond){
                                    currentPick.bond = pickingProxy.bond.toObject();
                                    currentPick.atom1 = pickingProxy.bond.atom1.toObject();
                                    currentPick.atom1.name = pickingProxy.bond.atom1.qualifiedName();
                                    currentPick.atom2 = pickingProxy.bond.atom2.toObject();
                                    currentPick.atom2.name = pickingProxy.bond.atom2.qualifiedName();
                                    pickingText = "Bond: " + currentPick.atom1.name + 
                                                    `(${pickingProxy.bond.atom1.index})` +
                                                    " - " + currentPick.atom2.name    +
                                                    `(${pickingProxy.bond.atom2.index})`;
                               }
                               
                               if(pickingProxy.instance){
                                    currentPick.instance = pickingProxy.instance;
                               }
                               var nComponents = this.stage.compList.length;
                               for(let i = 0; i < nComponents; i++){
                                    let comp = this.stage.compList[i];
                                    if(comp.uuid == pickingProxy.component.uuid){
                                        currentPick.component = i;
                                    }
                               }
                               this.model.set('picked', currentPick);
                               this.touch();
                               this.$pickingInfo.text(pickingText);
                            }
                    });
                """
            ]
