.. click:: deltona.commands.desktop:fix_mime_associations_main
   :prog: fix-mime-assocs
   :nested: full

Examples
--------

Reconcile one application using the standard desktop and MIME databases::

   fix-mime-assocs --application vim

Pass the option more than once to reconcile several applications::

   fix-mime-assocs --application vim --application org.kde.kwrite.desktop

Preview changes or use alternate files for testing::

   fix-mime-assocs --application vim --dry-run
   fix-mime-assocs --application vim --applications-dir ./applications \
     --mime-types ./mime/types --mimeapps ./mimeapps.list
