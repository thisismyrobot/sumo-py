import glob
import xml.dom.minidom


class Commands(object):
    """ Object dynamically populate with commands for Sumo.
    """
    def __init__(self):
        for xmlpath in glob.glob('sdk_xml/*.xml'):
            with open(xmlpath, 'rb') as xmlf:
                self._populate(xmlf.read())

    def _populate(self, xmlstr):
        dom = xml.dom.minidom.parseString(xmlstr)
        for project in dom.getElementsByTagName('project'):
            projectid = int(project.getAttribute('id'))

            for _class in project.getElementsByTagName('class'):

                classid = int(_class.getAttribute('id'))
                classname = _class.getAttribute('name')

                for (idx, cmd) in enumerate(_class.getElementsByTagName('cmd')):

                    cmdname = cmd.getAttribute('name')

                    print classname, cmdname, (projectid, classid, idx)


if __name__ == '__main__':
    commands = Commands()
