function updateSortRadioDetails(menu) {
    x = $(menu).find("input:checked");
    if (x.length == 0 ) {
        x = $(menu).find("input[value='n']");
        x.prop("checked", true);
    }
    x=x[0];
    $(menu).parent().find(".details").text($("label[for='"+x.id+"']").text());
}

$( document ).ready( function() {
    // Setup the sort ordering box
    $('.sort-order-box .dropdown-menu').on('click', function(e) {
        e.stopPropagation();
        updateSortRadioDetails(this);
       //$(this).closest("form").submit();
    });

    $('.sort-order-box .dropdown-menu').each( function() {
        updateSortRadioDetails(this);
    });

});