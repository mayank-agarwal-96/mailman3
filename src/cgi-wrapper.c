/* cgi-wrapper.c --- Generic wrapper that will take info from a environment
 * variable, and pass it to two commands.
 *
 * Copyright (C) 1998 by the Free Software Foundation, Inc.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software 
 * Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 *
 */

#include "common.h"

/* passed in by configure */
#define SCRIPTNAME  SCRIPT
#define LOG_IDENT   "Mailman cgi-wrapper (" ## SCRIPT ## ")"
#define LEGAL_PARENT_UID CGI_UID	     /* nobody's UID */
#define LEGAL_PARENT_GID CGI_GID	     /* nobody's GID */

const char* logident = LOG_IDENT;
const char* script = SCRIPTNAME;
const int parentuid = LEGAL_PARENT_UID;
const int parentgid = LEGAL_PARENT_GID;


int
main(int argc, char** argv, char** env) 
{
	int status;

	check_caller(logident, parentuid, parentgid);

	/* if we get here, the caller is OK */
	status = setuid(geteuid());
	if (status)
		fatal(logident, "%s", strerror(errno));

	status = run_script(script, argc, argv, env);
	fatal(logident, "%s", strerror(errno));
	return status;
}


/*
 * Local Variables:
 * c-file-style: "python"
 * End:
 */
